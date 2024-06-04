# sudo systemctl restart can-websocket-server.service
import time
import paho.mqtt.client as mqtt
import json
import socket
import struct
import sqlite3
import logging
from datetime import datetime
import subprocess

# Taken from the Global Source Addresses (B2) tab of the J1939DA_Feb24
j1939_SA={
0	:{'name':"Engine #1"},
1	:{'name':"Engine #2"},
2	:{'name':"Turbocharger"},
3	:{'name':"Transmission #1"},
4	:{'name':"Transmission #2"},
5	:{'name':"Shift Console - Primary"},
6	:{'name':"Shift Console - Secondary"},
7	:{'name':"Power TakeOff - (Main or Rear)"},
8	:{'name':"Axle - Steering"},
9	:{'name':"Axle - Drive #1"},
10	:{'name':"Axle - Drive #2"},
11	:{'name':"Brakes - System Controller"},
12	:{'name':"Brakes - Steer Axle"},
13	:{'name':"Brakes - Drive axle #1"},
14	:{'name':"Brakes - Drive Axle #2"},
15	:{'name':"Retarder - Engine"},
16	:{'name':"Retarder - Driveline"},
17	:{'name':"Cruise Control"},
18	:{'name':"Fuel System"},
19	:{'name':"Steering Controller"},
20	:{'name':"Suspension - Steer Axle"},
21	:{'name':"Suspension - Drive Axle #1"},
22	:{'name':"Suspension - Drive Axle #2"},
23	:{'name':"Instrument Cluster #1"},
24	:{'name':"Trip Recorder"},
25	:{'name':"Passenger-Operator Climate Control #1"},
26	:{'name':"Alternator/Electrical Charging System"},
27	:{'name':"Aerodynamic Control"},
28	:{'name':"Vehicle Navigation"},
29	:{'name':"Vehicle Security"},
30	:{'name':"Electrical System"},
31	:{'name':"Starter System"},
32	:{'name':"Tractor-Trailer Bridge #1"},
33	:{'name':"Body Controller"},
34	:{'name':"Auxiliary Valve Control or Engine Air System Valve Control"},
35	:{'name':"Hitch Control"},
36	:{'name':"Power TakeOff (Front or Secondary)"},
37	:{'name':"Off Vehicle Gateway"},
38	:{'name':"Virtual Terminal (in cab)"},
39	:{'name':"Management Computer #1"},
40	:{'name':"Cab Display #1"},
41	:{'name':"Retarder, Exhaust, Engine #1"},
42	:{'name':"Headway Controller"},
43	:{'name':"On-Board Diagnostic Unit"},
44	:{'name':"Retarder, Exhaust, Engine #2"},
45	:{'name':"Endurance Braking System"},
46	:{'name':"Hydraulic Pump Controller"},
47	:{'name':"Suspension - System Controller #1"},
48	:{'name':"Pneumatic - System Controller"},
49	:{'name':"Cab Controller - Primary"},
50	:{'name':"Cab Controller - Secondary"},
51	:{'name':"Tire Pressure Controller"},
52	:{'name':"Ignition Control Module #1"},
53	:{'name':"Ignition Control Module #2"},
54	:{'name':"Seat Control #1"},
55	:{'name':"Lighting - Operator Controls"},
56	:{'name':"Rear Axle Steering Controller #1"},
57	:{'name':"Water Pump Controller"},
58	:{'name':"Passenger-Operator Climate Control #2"},
59	:{'name':"Transmission Display - Primary"},
60	:{'name':"Transmission Display - Secondary"},
61	:{'name':"Exhaust Emission Controller"},
62	:{'name':"Vehicle Dynamic Stability Controller"},
63	:{'name':"Oil Sensor"},
64	:{'name':"Suspension - System Controller #2"},
65	:{'name':"Information System Controller #1"},
66	:{'name':"Ramp Control"},
67	:{'name':"Clutch/Converter Unit"},
68	:{'name':"Auxiliary Heater #1"},
69	:{'name':"Auxiliary Heater #2"},
70	:{'name':"Engine Valve Controller"},
71	:{'name':"Chassis Controller #1"},
72	:{'name':"Chassis Controller #2"},
73	:{'name':"Propulsion Battery Charger"},
74	:{'name':"Communications Unit, Cellular"},
75	:{'name':"Communications Unit, Satellite"},
76	:{'name':"Communications Unit, Radio"},
77	:{'name':"Steering Column Unit"},
78	:{'name':"Fan Drive Controller"},
79	:{'name':"Seat Control #2"},
80	:{'name':"Parking Brake Controller"},
81	:{'name':"Aftertreatment #1 system gas intake"},
82	:{'name':"Aftertreatment #1 system gas outlet"},
83	:{'name':"Safety Restraint System"},
84	:{'name':"Cab Display #2"},
85	:{'name':"Diesel Particulate Filter Controller"},
86	:{'name':"Aftertreatment #2 system gas intake"},
87	:{'name':"Aftertreatment #2 system gas outlet"},
88	:{'name':"Safety Restraint System #2"},
89	:{'name':"Atmospheric Sensor"},
90	:{'name':"Powertrain Control Module"},
91	:{'name':"Power Systems Manager"},
92	:{'name':"Engine Injection Control Module"},
93	:{'name':"Fire Protection System"},
94	:{'name':"Driver Impairment Device"},
95	:{'name':"Supply Equipment Communication Controller (SECC)"},
96	:{'name':"Vehicle Adapter Communication Controller (VACC)"},
97	:{'name':"Fuel Cell System"},
248	:{'name':"File Server / Printer"},
249	:{'name':"Off Board Diagnostic-Service Tool #1"},
250	:{'name':"Off Board Diagnostic-Service Tool #2"},
251	:{'name':"On-Board Data Logger"},
252	:{'name':"Reserved for Experimental Use"},
253	:{'name':"Reserved for OEM"},
254	:{'name':"Null Address"},
255	:{'name':"GLOBAL (All-Any Node)"}
}

# Configure logging
logging.basicConfig(level=logging.INFO, format='can_socket_server %(levelname)s:%(message)s')

logger=logging.getLogger()

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "j1939/stats"
MQTT_SIZE_TOPIC = "data/sizes"
MQTT_WATER_SENSOR_TOPIC = "data/water_sensors"

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

def publish_stats(client, cursor, table_name):
    
    # Python doesn't have a do loop, so we have t
    # Open a socket and bind to it from SocketCAN
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    interface = "can0"
    # Bind to the interface
    sock.bind((interface,))
    
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
    table_data = []
    start_time = time.time()
    size_start_time = start_time
    water_sensor_start_time = start_time
    water_sensor_data = {}
    last_water_sensor_freshness = 0
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
    
        #Parse the bytes into a CAN message
        can_id, can_dlc, can_data, can_id_string = unpack_CAN(can_packet)
        can_data_string = " ".join(["{:02X}".format(b) for b in can_data])
                                   
        #Parse the CAN ID into J1939
        priority,pgn,da,sa = get_j1939_from_id(can_id)

        table_data.append((can_time, interface, pgn, sa, da, can_id, can_dlc, can_data_string))
        
        if can_id == 0x19F21139:
            freshness = struct.unpack("<L",can_data[4:8])[0]
            if freshness > last_water_sensor_freshness:
                # update the information with new data   
                water_sensor_data['center'] = bool(can_data[0])
                water_sensor_data['port'] = bool(can_data[1])
                water_sensor_data['starboard'] = bool(can_data[2])
            else:
                water_sensor_data['center':None]
                water_sensor_data['port':None]
                water_sensor_data['starboard':None]
            last_water_sensor_freshness = freshness

        #Make a summary of the CAN messages.
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
            
    
        table_sizes[table_name]+=1
        if (can_time - water_sensor_start_time) > 0.73:
            water_sensor_start_time = can_time
            client.publish(MQTT_WATER_SENSOR_TOPIC, json.dumps(water_sensor_data,sort_keys=True))
            logger.debug(f"Published to {MQTT_WATER_SENSOR_TOPIC}: {json.dumps(water_sensor_data,sort_keys=True)}")

        if (can_time - start_time) > 1.51:
            start_time = time.time()
            client.publish(MQTT_TOPIC, json.dumps(data,sort_keys=True))
            try:
                cursor.execute('BEGIN;')
                # ITERATE through the list of stored CAN data
                for item in table_data:
                    cursor.execute(f'''
                    INSERT INTO {table_name} (timestamp, interface, pgn, sa, da, can_id, can_dlc, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',(item))
                # Update the number of messages
                cursor.execute('''
                    UPDATE table_metadata 
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

        if (can_time - size_start_time) > 1.91:
            size_start_time = time.time()
            client.publish(MQTT_SIZE_TOPIC, json.dumps(table_sizes,sort_keys=True))
            logger.debug(f"Published to {MQTT_SIZE_TOPIC}:\n {json.dumps(table_sizes,indent=2,sort_keys=True)}")
            
if __name__ == "__main__":    
    # Setup a perpetual loop to catch issues with socketCAN.
    # Other users can take down and bring up CAN, so the socket will fail and 
    # we need to restart again.
    
    #Setup the CAN channel to restart. 
    try:
        command = f"sudo ip link set can0 down"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        command = f"sudo ip link set can0 up type can bitrate 250000 restart-ms 100"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(result.stderr)
    except Exception as e:
        logger.error(str(e))

    while True:
        logger.info("Starting CAN Server with MQTT and SQLite")
        # Connect to the broker.
        # mosquitto should be running
        client = mqtt.Client()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        logger.info(f"MQTT Connected to {MQTT_BROKER} on port {MQTT_PORT}")

        # Connect to the database
        conn = sqlite3.connect('can_messages.db')
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA cache_size=10000;')
        logger.info(f"Connected can_messages.db")
        
        # Create the metadata table if it doesn't exist
        conn.execute('''
        CREATE TABLE IF NOT EXISTS table_metadata (
            table_name TEXT PRIMARY KEY,
            creation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            channel TEXT,
            bitrate INTEGER,
            num_messages INTEGER      
        )
        ''')
        cursor = conn.cursor()
        
        logger.info(f"Created table_metadata in can_messages.db")
        #Get a dozen Existing tables:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 12")
        rows = cursor.fetchall()
        
        tables = [row[0] for row in rows if row[0] != 'sqlite_sequence']

        # Get table sizes
        table_sizes = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cursor.fetchone()[0]   
            table_sizes[table]=row_count

        client.publish(MQTT_SIZE_TOPIC, json.dumps(table_sizes))
        logger.info(f"Published table sizes to {MQTT_SIZE_TOPIC}")

        table_name = f'{datetime.now().strftime("J1939_%Y%m%d_%H%M%S")}'
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
            conn.commit()
            logger.info(f"Created Table {table_name} in database.")
        except sqlite3.Error as e:
            logger.error(str(e))
            time.sleep(5)
        except Exception as e:
            logger.warning(repr(e))
        
        #There should be no error now and both CAN and SQLite are up
        publish_stats(client, cursor, table_name)
        
        # Close down the database connection.
        cursor.close()
        conn.close()

        # Close down the MQTT connection
        client.disconnect()
        #pause before restarting
        time.sleep(1)