import asyncio
import websockets
import json
import socket
import struct
import sqlite3
import logging
import subprocess
import queue
import threading
import sys
import time
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='can_socket_server:%(message)s')

logger = logging.getLogger()

WEBSOCKET_HOST = "0.0.0.0"
WEBSOCKET_PORT = 8765
STATS_TOPIC = "cansocket/stats"
SIZE_TOPIC = "data/sizes"
WATER_SENSOR_TOPIC = "data/water_sensors"

MAX_TABLE_SIZE = 10000000
UPDATE_PERIOD = .75  # second
freshness_timeout_ms = 5000

# To match this data structure, the following struct format can be used:
can_frame_format = "<lB3x8s"

# Parse J1939 protocol data unit information from the ID using bit masks and shifts
PRIORITY_MASK = 0x1C000000
EDP_MASK = 0x02000000
DP_MASK = 0x01000000
PF_MASK = 0x00FF0000
PS_MASK = 0x0000FF00
SA_MASK = 0x000000FF
PDU1_PGN_MASK = 0x03FF0000
PDU2_PGN_MASK = 0x03FFFF00

def get_j1939_from_id(can_id):
    # priority
    priority = (PRIORITY_MASK & can_id) >> 26

    # Protocol Data Unit (PDU) Format
    PF = (can_id & PF_MASK) >> 16

    # Determine the Parameter Group Number and Destination Address
    if PF >= 0xF0:  # 240
        # PDU 2 format, include the PS as a group extension
        DA = 255
        PGN = (can_id & PDU2_PGN_MASK) >> 8
    else:
        PGN = (can_id & PDU1_PGN_MASK) >> 8
        DA = (can_id & PS_MASK) >> 8
    # Source address
    SA = (can_id & SA_MASK)
    return priority, PGN, DA, SA

# Make a CAN reading function
def unpack_CAN(can_packet):
    can_id, can_dlc, can_data = struct.unpack(can_frame_format, can_packet)
    extended_frame = bool(can_id & socket.CAN_EFF_FLAG)
    if extended_frame:
        can_id &= socket.CAN_EFF_MASK
        can_id_string = "{:08X}".format(can_id)
    else:  # Standard Frame
        can_id &= socket.CAN_SFF_MASK
        can_id_string = "{:03X}".format(can_id)
    return can_id, can_dlc, can_data, can_id_string

def get_can_stats():
    # Command to get CAN statistics with detailed information
    command = "ip -details -statistics link show can0"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        return
    # Parsing the result
    stats = {}
    stat_lines = result.stdout.split('\n')
    for line in range(len(stat_lines)):
        if 'can state' in stat_lines[line]:
            stats['CANstate'] = stat_lines[line].strip().split()[2]
        elif 'bitrate' in stat_lines[line]:
            bitrate = int(stat_lines[line].strip().split()[1]) // 1000
            stats['CANbitrate'] = f"{bitrate}k"
        elif 'RX:' in stat_lines[line]:
            rx_header = stat_lines[line].strip().split()[1:]  # Remove the "RX:"
            rx_line = stat_lines[line + 1].strip().split()
            for k, v in zip(rx_header, rx_line):
                stats['CANRX' + k] = "{:0,.3f}kB".format(int(v) / 1024)
        elif 'TX:' in stat_lines[line]:
            tx_header = stat_lines[line].strip().split()[1:]  # Remove the "TX:"
            tx_line = stat_lines[line + 1].strip().split()
            for k, v in zip(tx_header, tx_line):
                stats['CANTX' + k] = v
    return stats

def can_reader(can_queue, stop_event, interface="can0"):
    # Open a socket and bind to it from SocketCAN
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    # Bind to the interface
    sock.bind((interface,))
    while not stop_event.is_set():
        try:
            can_packet = sock.recv(16)
            # get the system time as soon after the message is read
            can_time = time.time()  # This is jittery and may not reflect actual bus time, but it's close.

            # Parse the bytes into a CAN message
            can_id, can_dlc, can_data, can_id_string = unpack_CAN(can_packet)
            can_data_string = " ".join(["{:02X}".format(b) for b in can_data])

            # Parse the CAN ID into J1939
            priority, pgn, da, sa = get_j1939_from_id(can_id)
            can_queue.put((can_time, interface, pgn, sa, da, can_id, can_dlc, can_data_string, can_data))
        except OSError as e:
            logger.info(f"Reading {interface} failed with error {e}")
            time.sleep(1)
            sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            sock.bind((interface,))

async def can_processor(can_queue, ws, cursor, conn, stop_event):
    data = {"Source": {}}
    table_data = []
    start_time = time.time()
    size_start_time = start_time
    water_sensor_start_time = start_time
    water_sensor_data = {}
    freshness = 0
    last_water_sensor_freshness = 0
    water_sensor_data_time = 0

    table_sizes = make_table(cursor, conn)
    table_name = list(table_sizes.keys())[0]

    while not stop_event.is_set():
        try:
            can_time, interface, pgn, sa, da, can_id, can_dlc, can_data_string, can_data = can_queue.get(timeout=1)
        except queue.Empty:
            #still send information out
            water_sensor_data = {'center': None, 'port': None, 'starboard': None}
            await ws.send(json.dumps({'topic': WATER_SENSOR_TOPIC, 'data': water_sensor_data}))
            await ws.send(json.dumps({'topic': SIZE_TOPIC, 'data': table_sizes}))
            await ws.send(json.dumps({'topic': STATS_TOPIC, 'data': get_can_stats()}))
            continue

        # Since a message was received, increment the table size and see if a new table is needed.
        table_sizes[table_name] += 1
        if table_sizes[table_name] > MAX_TABLE_SIZE:
            table_sizes = make_table(cursor, conn)
            table_name = list(table_sizes.keys())[0]

        table_data.append((can_time, interface, pgn, sa, da, can_id, can_dlc, can_data_string, can_data))

        if can_id == 0x19F21139:
            water_sensor_data_time = can_time
            freshness = struct.unpack("<L", can_data[4:8])[0]
            if freshness > last_water_sensor_freshness:  # new message
                last_water_sensor_freshness = freshness
                water_sensor_data['center'] = bool(can_data[0])
                water_sensor_data['port'] = bool(can_data[1])
                water_sensor_data['starboard'] = bool(can_data[2])
            else:
                water_sensor_data = {'center': None, 'port': None, 'starboard': None}

        if (can_time - water_sensor_start_time) > 0.73:
            water_sensor_start_time = can_time
            if (can_time - water_sensor_data_time) > 1:
                water_sensor_data = {'center': None, 'port': None, 'starboard': None}
                last_water_sensor_freshness = 0

            await ws.send(json.dumps({'topic': WATER_SENSOR_TOPIC, 'data': water_sensor_data}))

        if (can_time - start_time) > 0.91:
            start_time = time.time()
            try:
                cursor.execute('BEGIN;')
                for item in table_data:
                    cursor.execute(f'''
                    INSERT INTO {table_name} (timestamp, interface, pgn, sa, da, can_id, can_dlc, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (item))
                cursor.execute('COMMIT;')
            except sqlite3.Error as e:
                cursor.execute('ROLLBACK;')
                logger.warning(f"sqlite database transaction error: {e}")
            finally:
                table_data = []

        if (can_time - size_start_time) > .87:
            size_start_time = time.time()
            await ws.send(json.dumps({'topic': SIZE_TOPIC, 'data': table_sizes}))
            await ws.send(json.dumps({'topic': STATS_TOPIC, 'data': get_can_stats()}))
            

def make_table(cursor, conn):
    table_name = f'{datetime.now().strftime("J1939_%Y%m%d_%H%M%S")}'
    try:
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp FLOAT,
                interface TEXT,
                pgn INTEGER,
                sa INTEGER,
                da INTEGER,
                can_id TEXT,
                can_dlc INTEGER,
                data TEXT
            )
        ''')
        conn.commit()
        logger.info(f"Created Table {table_name} in database.")
        return {table_name: 0}
    except sqlite3.Error as e:
        logger.error(str(e))
        time.sleep(5)
    except Exception as e:
        logger.warning(repr(e))

async def websocket_handler(websocket, path):
    conn = sqlite3.connect('can_messages.db')
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA cache_size=10000;')
    logger.info(f"Connected can_messages.db")
    
    cursor = conn.cursor()
    can_queue = queue.Queue()
    stop_event = threading.Event()
    interface = "can0"

    reader_thread = threading.Thread(target=can_reader, args=(can_queue, stop_event, interface), daemon=True)
    reader_thread.start()
    
    try:
        await can_processor(can_queue, websocket, cursor, conn, stop_event)
        reader_thread.join()
    except Exception as e:
        logger.error(f"Exception in can_processor: {str(e)}")
    finally:
        logger.info("stopping threads")
        stop_event.set()

        cursor.close()
        conn.close()
        await websocket.close()

async def main():
    while True:
        try:
            server = await websockets.serve(websocket_handler, WEBSOCKET_HOST, WEBSOCKET_PORT)
            logger.info(f"WebSocket Server started at ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
            await server.wait_closed()
            # async with websockets.serve(websocket_handler, WEBSOCKET_HOST, WEBSOCKET_PORT):
            #     logger.info(f"WebSocket Server started at ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
            #     await asyncio.Future()  # Run forever
        except Exception as e:
            logger.error(repr(e))
        finally:
            logger.info("Restarting websocket server.")

if __name__ == "__main__":
    try:
        interface = "can0"
        command = f"sudo ip link set {interface} down"
        subprocess.run(command, shell=True, capture_output=True, text=True)
        command = f"sudo ip link set {interface} up type can bitrate 250000 restart-ms 100"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(result.stderr)
    except Exception as e:
        logger.error(str(e))
        logger.error("Quitting can_socket_server.py")
        sys.exit()

    asyncio.run(main())

    
    #Setup some defaults
    # volts = "N/A"
    # rpm = "N/A"
    # port_water_sensor = "N/A"
    # center_water_sensor = "N/A"
    # starboard_water_sensor = "N/A"
    # port_fill_level = "N/A"
    # center_fill_level = "N/A"
    # starboard_fill_level = "N/A"
    # port_fill_state = "N/A"
    # center_fill_state = "N/A"
    # starboard_fill_state = "N/A"
    # port_fill_timer = "N/A"
    # center_fill_timer = "N/A"
    # starboard_fill_timer = "N/A"
    # port_switch_state = "N/A"
    # center_switch_state = "N/A"
    # starboard_switch_state = "N/A"
    # center_trim_tab_position = "N/A"
    # center_trim_tab_switch_state = "N/A"
    
#     data = {"Source":{}}
#     table_data = []
#     start_time = time.time()
#     size_start_time = start_time
#     water_sensor_start_time = start_time
#     water_sensor_data = {}
#     freshness = 0 # 0xFFFFFFFF # the highest 32 bit unsigned integer
#     last_water_sensor_freshness = 0
#     water_sensor_data_time = 0    
#     loop_time = start_time
#     last_loop_time = 0
#     while True:
#         # Read the message from the newtork
#         try:
#             can_packet = sock.recv(16)
#         except socket.timeout:
#             water_sensor_data = {'center':None, 'port':None, 'starboard':None}
#             client.publish(MQTT_WATER_SENSOR_TOPIC, json.dumps(water_sensor_data))
#             continue
#         except OSError as e:
#             water_sensor_data = {'center':None, 'port':None, 'starboard':None}
#             client.publish(MQTT_WATER_SENSOR_TOPIC, json.dumps(water_sensor_data))
#             logger.info(f"Reading {interface} failed with error {e}")
#             time.sleep(1)
#             sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
#             # Bind to the interface
#             sock.bind((interface,))
#             logger.debug(sock)
#             continue
        
#         #Since a message was receive, increment the table size
#         table_sizes[table_name]+=1

#         # get the system time as soon after the message is read
#         can_time = time.time() #This is jittery and may not reflect actual bus time, but it's close.
        
#         #Parse the bytes into a CAN message
#         can_id, can_dlc, can_data, can_id_string = unpack_CAN(can_packet)
#         can_data_string = " ".join(["{:02X}".format(b) for b in can_data])
                                   
#         #Parse the CAN ID into J1939
#         priority,pgn,da,sa = get_j1939_from_id(can_id)

#         table_data.append((can_time, interface, pgn, sa, da, can_id, can_dlc, can_data_string))
        
#         if can_id == 0x19F21139:
#             water_sensor_data_time = can_time
#             freshness = struct.unpack("<L",can_data[4:8])[0]
#             if (freshness > last_water_sensor_freshness): #new message
#                 last_water_sensor_freshness = freshness
#                 water_sensor_data['center'] = bool(can_data[0])
#                 water_sensor_data['port'] = bool(can_data[1])
#                 water_sensor_data['starboard'] = bool(can_data[2])
#             else:
#                 water_sensor_data =  {'center':None, 'port':None, 'starboard':None}
                
#             logger.debug(f"freshness: {freshness}, center: {can_data[0]}, port: {can_data[1]}, starboard: {can_data[2]} ")
            
        
#         if (can_time - water_sensor_start_time) > .73:
#             water_sensor_start_time = can_time
#             logger.debug(f"difference {can_time - water_sensor_data_time}")
#             if (can_time - water_sensor_data_time) > 1:
#                 # The timeout was exceeded, so the data is not fresh
#                 water_sensor_data =  {'center':None, 'port':None, 'starboard':None}
#                 last_water_sensor_freshness = 0
            
#             client.publish(MQTT_WATER_SENSOR_TOPIC, json.dumps(water_sensor_data))
#             logger.debug(f"Published to {MQTT_WATER_SENSOR_TOPIC}: {json.dumps(water_sensor_data)}")

#         if (can_time - start_time) > .91:
#             start_time = time.time()
#             try:
#                 cursor.execute('BEGIN;')
#                 # ITERATE through the list of stored CAN data
#                 for item in table_data:
#                     cursor.execute(f'''
#                     INSERT INTO {table_name} (timestamp, interface, pgn, sa, da, can_id, can_dlc, data)
#                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',(item))
#                 cursor.execute('COMMIT;')
#             except sqlite3.Error as e:
#                 # Rollback the transaction in case of error
#                 cursor.execute('ROLLBACK;')
#                 logger.warning(f"sqlite database transaction error: {e}")
#             finally:
#                 #Reset the table data 
#                 table_data = []

#         if (can_time - size_start_time) > 1.91:
#             size_start_time = time.time()
#             client.publish(MQTT_SIZE_TOPIC, json.dumps(table_sizes,sort_keys=True))
#             logger.debug(f"Published to {MQTT_SIZE_TOPIC}: {json.dumps(table_sizes,)}")
        

# if __name__ == "__main__":    
#     # Setup a perpetual loop to catch issues with socketCAN.
#     # Other users can take down and bring up CAN, so the socket will fail and 
#     # we need to restart again.
    
#     #Setup the CAN channel to restart. 
#     try:
#         command = f"sudo ip link set can0 down"
#         result = subprocess.run(command, shell=True, capture_output=True, text=True)
#         command = f"sudo ip link set can0 up type can bitrate 250000 restart-ms 100"
#         result = subprocess.run(command, shell=True, capture_output=True, text=True)
#         if result.returncode != 0:
#             logger.warning(result.stderr)
#     except Exception as e:
#         logger.error(str(e))

#     while True:
#         logger.info("Starting CAN Server with MQTT and SQLite")
#         # Connect to the broker.
#         # mosquitto should be running
#         client = mqtt.Client()
#         client.connect(MQTT_BROKER, MQTT_PORT, 60)
#         logger.info(f"MQTT Connected to {MQTT_BROKER} on port {MQTT_PORT}")

#         # Connect to the database
#         conn = sqlite3.connect('can_messages.db')
#         conn.execute('PRAGMA journal_mode=WAL;')
#         conn.execute('PRAGMA cache_size=10000;')
#         logger.info(f"Connected can_messages.db")
        
#         cursor = conn.cursor()
        
#         table_name = f'{datetime.now().strftime("J1939_%Y%m%d_%H%M%S")}'
#         table_sizes = {table_name: 0}
#         try:
#             cursor.execute(f'''
#                 CREATE TABLE IF NOT EXISTS {table_name} (
#                     id INTEGER PRIMARY KEY AUTOINCREMENT,
#                     timestamp FLOAT,
#                     interface TEXT,
#                     pgn INTEGER,
#                     sa INTEGER,
#                     da INTEGER,
#                     can_id TEXT,
#                     can_dlc INTEGER,
#                     data TEXT
#                 )
#             ''')
#             conn.commit()
#             logger.info(f"Created Table {table_name} in database.")
#         except sqlite3.Error as e:
#             logger.error(str(e))
#             time.sleep(5)
#         except Exception as e:
#             logger.warning(repr(e))
        
#         #There should be no error now and both CAN and SQLite are up
#         publish_stats(client, cursor, table_name)
        
#         # Close down the database connection.
#         cursor.close()
#         conn.close()

#         # Close down the MQTT connection
#         client.disconnect()
#         #pause before restarting
#         time.sleep(1)