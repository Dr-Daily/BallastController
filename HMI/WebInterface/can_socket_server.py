# sudo systemctl restart can-websocket-server.service
import time
import paho.mqtt.client as mqtt
import json
import socket
import struct
import sqlite3
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

logger=logging.getLogger()

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "j1939/stats"
MQTT_SIZE_TOPIC = "data/sizes"

UPDATE_PERIOD = .75 #second

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

j1939_SA={0:{'name':"Engine #1"},
          3:{'name':"Transmission"},
          11:{'name':"Brake - System Controller"},
          15:{'name':"Retarder"}
          }

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

def publish_stats(client, cursor, table_name):
    try:
        # Open a socket and bind to it from SocketCAN
        sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        interface = "can0"
        # Bind to the interface
        sock.bind((interface,))
    except OSError:
        #Wait for the network to come back up.
        time.sleep(3)
        return
    except Exception as e:
        logger.warning(repr(e))
        return
    
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
    
    data = {"Source":{}}
    start_time = time.time()
    size_start_time = start_time
    while True:
        # Read the message from the newtork
        try:
            can_packet = sock.recv(16)
        except OSError:
            logger.debug("Reading the socket failed.")
            logger.debug(sock)
            logger.debug("Trying to establish another socket.")
            time.sleep(1)
            sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            interface = "can0"
            # Bind to the interface
            sock.bind((interface,))
            logger.debug(sock)
            continue
        
        can_time = time.time() #This is jittery.
    
        #Parse the bytes into a CAN message
        can_id, can_dlc, can_data, can_id_string = unpack_CAN(can_packet)
        can_data_string = " ".join(["{:02X}".format(b) for b in can_data])
                                   
        #Parse the CAN ID into J1939
        priority,pgn,da,sa = get_j1939_from_id(can_id)


        if sa in data["Source"]:
            data["Source"][sa]['count']+=1
        else:
            data["Source"][sa]={'count': 1}
            data["Source"][sa]['address'] = sa
            data["Source"][sa]['pgns'] = {}
            try:
                data["Source"][sa]['name'] = j1939_SA[sa]['name']
            except KeyError:
                data["Source"][sa]['name'] = "Unknown"
        
        if pgn in data["Source"][sa]['pgns']:
            data["Source"][sa]['pgns'][pgn]['count']+=1
            data["Source"][sa]['pgns'][pgn]['time_delta'] = "{:d}ms".format(
                int((can_time - data["Source"][sa]['pgns'][pgn]['time'])*1000))
        else:
            data["Source"][sa]['pgns'][pgn] = {'count': 1}
            data["Source"][sa]['pgns'][pgn]['id']=can_id_string
            data["Source"][sa]['pgns'][pgn]['time_delta']= 0
            data["Source"][sa]['pgns'][pgn]['da']=da
        
        data["Source"][sa]['pgns'][pgn]['data'] = can_data_string
        data["Source"][sa]['pgns'][pgn]['time']= can_time
            
        cursor.execute(f'''
            INSERT INTO {table_name} (timestamp, pgn, sa, da, can_id, can_dlc, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (can_time, pgn, sa, da, can_id_string, can_dlc, can_data_string))

        conn.commit()
        table_sizes[table_name]+=1

        if (can_time - start_time) > UPDATE_PERIOD:
            start_time = time.time()
            client.publish(MQTT_TOPIC, json.dumps(data))
            logger.info(f"Published to {MQTT_TOPIC}")

        if (can_time - size_start_time) > 3.27:
            size_start_time = time.time()
            client.publish(MQTT_SIZE_TOPIC, json.dumps(table_sizes))
            logger.info(f"Published to {MQTT_SIZE_TOPIC}")
            
if __name__ == "__main__":

    # Connect to the broker.
    # mosquitto should be running
    client = mqtt.Client()
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    
    # Setup a perpetual loop to catch issues with socketCAN.
    # Other users can take down and bring up CAN, so the socket will fail and 
    # we need to restart again.
    while True:
        
        # Once the network is alive, then we can create a new table in the database for CAN.
        conn = sqlite3.connect('can_messages.db')
        cursor = conn.cursor()

        #Get Existing tables:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        rows = cursor.fetchall()
        
        tables = [row[0] for row in rows if row[0] != 'sqlite_sequence']

        # Get table sizes
        table_sizes = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cursor.fetchone()[0]   
            table_sizes[table]=row_count

        client.publish(MQTT_SIZE_TOPIC, json.dumps(table_sizes))
        logger.info(f"Published to {MQTT_SIZE_TOPIC}")

        table_name = f'{datetime.now().strftime("J1939_%Y%m%d_%H%M%S")}'
        table_sizes[table_name]=0
        try:
            cursor.execute(f'''
                CREATE TABLE {table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp FLOAT,
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
        publish_stats(client, cursor, table_name)
        cursor.close()
        conn.close()