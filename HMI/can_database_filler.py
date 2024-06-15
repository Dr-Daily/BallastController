import time
import socket
import struct
import sqlite3
import logging
from datetime import datetime
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO, format='can_socket_server %(levelname)s:%(message)s')
logger=logging.getLogger()

UPDATE_PERIOD = .91 #second
CAN_INTERFACE = 'can0'
CAN_BITRATE = 250000

# To match this data structure, the following struct format can be used:
can_frame_format = "<lB3x8s"

#parse J1939 protocol data unit information from the ID using bit masks and shifts
PRIORITY_MASK = 0x1C000000
EDP_MASK      = 0x02000000
DP_MASK       = 0x01000000
PF_MASK       = 0x00FF0000
PS_MASK       = 0x0000FF00
SA_MASK       = 0x000000FF
PDU1_PGN_MASK = 0x03FF0000
PDU2_PGN_MASK = 0x03FFFF00

def get_j1939_from_id(can_id):
    #priority
    priority = (PRIORITY_MASK & can_id) >> 26

    # Protocol Data Unit (PDU) Format
    PF = (can_id & PF_MASK) >> 16
        
    # Determine the Parameter Group Number and Destination Address
    if PF >= 0xF0: #240
        # PDU 2 format, include the PS as a group extension
        DA = 255
        PGN = (can_id & PDU2_PGN_MASK) >> 8
    else:
        PGN = (can_id & PDU1_PGN_MASK) >> 8
        DA = (can_id & PS_MASK) >> 8
    # Source address
    SA = (can_id & SA_MASK)   
    return priority,PGN,DA,SA

#Make a CAN reading function
def unpack_CAN(can_packet):
    can_id, can_dlc, can_data = struct.unpack(can_frame_format, can_packet)
    extended_frame = bool(can_id & socket.CAN_EFF_FLAG)
    if extended_frame:
        can_id &= socket.CAN_EFF_MASK
        can_id_string = "{:08X}".format(can_id)
    else: #Standard Frame
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
            bitrate = int(stat_lines[line].strip().split()[1])//1000
            stats['CANbitrate'] = f"{bitrate}k"
        elif 'RX:' in stat_lines[line]:
            rx_header = stat_lines[line].strip().split()[1:] #Remove the "RX:"
            rx_line = stat_lines[line+1].strip().split()
            for k,v in zip(rx_header,rx_line):
                stats['CANRX'+k] = "{:0,.3f}kB".format(int(v)/1024)
        elif 'TX:' in stat_lines[line]:
            tx_header = stat_lines[line].strip().split()[1:] #Remove the "TX:"
            tx_line = stat_lines[line+1].strip().split()
            for k,v in zip(tx_header,tx_line):
                stats['CANTX'+k] = v
    return stats

def publish_stats(cursor, table_name, meta_data_table_name):
    
    # Python doesn't have a do loop, so we have t
    # Open a socket and bind to it from SocketCAN
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    interface = "can1"
    # Bind to the interface
    sock.bind((interface,))
    
    data = {"Source":{}}
    table_data = []
    start_time = time.time()
    size_start_time = start_time
    water_sensor_start_time = start_time
    water_sensor_data = {}
    last_water_sensor_freshness = 0
    loop_time = start_time
    last_loop_time = 0
    while True:
        # Read the message from the newtork
        try:
            can_packet = sock.recv(16)
        except OSError as e:
            logger.info(f"Reading {interface} failed with error {e}")
            time.sleep(1)
            sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            # Bind to the interface
            sock.bind((interface,))
            logger.debug(sock)
            continue
        
        # get the system time as soon after the message is read
        can_time = time.time() #This is jittery and may not reflect actual bus time, but it's close.
        loop_time = int((can_time - last_loop_time)*1000000)
        last_loop_time = can_time
        #Parse the bytes into a CAN message
        can_id, can_dlc, can_data, can_id_string = unpack_CAN(can_packet)

        can_data_string = " ".join(["{:02X}".format(b) for b in can_data])
                                   
        #Parse the CAN ID into J1939
        priority,pgn,da,sa = get_j1939_from_id(can_id)
        
        #Make a summary of the CAN messages.
        #Move this to the database
        if sa in data["Source"]:
            data["Source"][sa]['count']+=1
        else:
            data["Source"][sa] = {'count': 1}
            data["Source"][sa]['address'] = sa
            data["Source"][sa]['pgns'] = {}
            
        if pgn in data["Source"][sa]['pgns']:
            data["Source"][sa]['pgns'][pgn]['count']+=1
            data["Source"][sa]['pgns'][pgn]['time_delta'] = "{:d}ms".format(
                int((can_time - data["Source"][sa]['pgns'][pgn]['time'])*1000))
        else:
            data["Source"][sa]['pgns'][pgn] = {'count': 1}
            data["Source"][sa]['pgns'][pgn]['time_delta']= 0
        
        data["Source"][sa]['pgns'][pgn]['time'] = can_time
        data["Source"][sa]['pgns'][pgn]['id']   = can_id_string
        data["Source"][sa]['pgns'][pgn]['da']   = da
        data["Source"][sa]['pgns'][pgn]['data'] = can_data_string

        table_data.append((can_time, interface, pgn, sa, da, can_id, can_dlc, can_data_string))    
        table_sizes[table_name]+=1
        
        source_string = ''
        if (can_time - start_time) > UPDATE_PERIOD:
            for src,vals in sorted(data["Source"].items()):
                source_string += "{:02x} ({}): {}, ".format(src,vals['name'],vals["count"]) 
            logger.info(source_string)
            start_time = time.time()
            try:
                cursor.execute('BEGIN;')
                # ITERATE through the list of stored CAN data
                for item in table_data:
                    cursor.execute(f'''
                    INSERT INTO {table_name} (timestamp, interface, pgn, sa, da, can_id, can_dlc, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',(item))
                # Update the number of messages
                cursor.execute(f'''
                    UPDATE {meta_data_table_name} 
                    SET num_messages = ? 
                    WHERE table_name = ?
                ''', (table_sizes[table_name], table_name))
                cursor.execute('COMMIT;')
            except sqlite3.Error as e:
                # Rollback the transaction in case of error
                cursor.execute('ROLLBACK;')
                logger.warning(f"sqlite database transaction error: {e}")
            finally:
                #Reset the table data 
                table_data = []

if __name__ == "__main__":    
    # Setup a perpetual loop to catch issues with socketCAN.
    # Other users can take down and bring up CAN, so the socket will fail and 
    # we need to restart again.
    
    #Setup the CAN channel to restart. 
    try:
        command = f"sudo ip link set {CAN_INTERFACE} down"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        command = f"sudo ip link set {CAN_INTERFACE} up type can bitrate {CAN_BITRATE} restart-ms 100"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(result.stderr)
    except Exception as e:
        logger.error(str(e))

    while True:
        logger.info("Starting CAN Server with SQLite")
    
        # Connect to the database
        conn = sqlite3.connect('can_messages.db')
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA cache_size=8000;')
        logger.info(f"Connected can_messages.db")
        cursor = conn.cursor()
    
        # Get table sizes
        table_sizes = {}
      
        table_name = f'{datetime.now().strftime("J1939_%Y%m%d_%H%M%S")}'
        meta_data_table_name = table_name + "_meta"
        table_sizes[table_name]=0
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
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {meta_data_table_name} (
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
        except sqlite3.Error as e:
            logger.error(str(e))
            time.sleep(5)
        except Exception as e:
            logger.warning(repr(e))
        
        #There should be no error now and both CAN and SQLite are up
        publish_stats(cursor, table_name)
        
        # Close down the database connection.
        cursor.close()
        conn.close()

        #pause before restarting
        time.sleep(1)