#!/python
from flask import Flask, jsonify, render_template, request, send_file, Response
from flask_socketio import SocketIO, emit #sudo apt install python3-flask-socketio -y
import csv
import io
import subprocess
import humanize #sudo apt install python3-humanize -y
import psutil #sudo apt install python3-psutil -y
import socket
import sqlite3
import re
import time
import threading
import queue
import logging
import struct
import math

DATABASE = 'can_messages.db'

app = Flask(__name__)
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

# After making changes, run 
# sudo systemctl restart flask-app.service
# to restart.

# To debug, run 
# sudo systemctl status flask-app.service
#
# If that's not enough, run
# journalctl -r 
# to get the tail end of the system journal

# ── shared state ──────────────────────────────────────────────────────────────
heading_deg          = 0.0     # 0-359.999  (0 = true north)
rudder_angle_deg     = 0.0     # positive = starboard, negative = port






hdg_lock   = threading.Lock()  # protect concurrent updates

# Taken from the Global Source Addresses (B2) tab of the J1939DA_Feb24
j1939_SA={
0	:{'name':"Engine #1"},
1	:{'name':"Engine #2"},
2	:{'name':"Turbocharger"},
3	:{'name':"Transmission #1"},
4	:{'name':"Transmission #2"},
5	:{'name':"Shift Console #1"},
6	:{'name':"Shift Console #2"},
7	:{'name':"Power TakeOff"},
8	:{'name':"Axle-Steering"},
9	:{'name':"Axle-Drive #1"},
10	:{'name':"Axle-Drive #2"},
11	:{'name':"Brake Controller"},
12	:{'name':"Brakes-Steer"},
13	:{'name':"Brakes-Drive #1"},
14	:{'name':"Brakes-Drive #2"},
15	:{'name':"Retarder-Engine"},
16	:{'name':"Retarder-Driveline"},
17	:{'name':"Cruise Control"},
18	:{'name':"Fuel System"},
19	:{'name':"Steering Controller"},
20	:{'name':"Suspension-Steer"},
21	:{'name':"Suspension-Drive #1"},
22	:{'name':"Suspension-Drive#2"},
23	:{'name':"Inst. Cluster"},
24	:{'name':"Trip Recorder"},
25	:{'name':"Climate Control #1"},
26	:{'name':"Alternator"},
27	:{'name':"Aerodynamic Control"},
28	:{'name':"Navigation"},
29	:{'name':"Security"},
30	:{'name':"Electrical System"},
31	:{'name':"Starter System"},
32	:{'name':"Trailer Bridge #1"},
33	:{'name':"Body Controller"},
34	:{'name':"Aux. Valve Control"},
35	:{'name':"Hitch Control"},
36	:{'name':"PTO2 2"},
37	:{'name':"Off Vehicle Gateway"},
38	:{'name':"Virtual Terminal"},
39	:{'name':"Mgt. Computer #1"},
40	:{'name':"Cab Display #1"},
41	:{'name':"Exhaust Retarder 1"},
42	:{'name':"Headway Controller"},
43	:{'name':"On-Board Diagnostic"},
44	:{'name':"Exhaust Retarder 2"},
45	:{'name':"Endurance Braking"},
46	:{'name':"Hydraulic Pump"},
47	:{'name':"Suspension 1"},
48	:{'name':"Pneumatics"},
49	:{'name':"Cab Controller 1"},
50	:{'name':"Cab Controller 2"},
51	:{'name':"Tire Pressure"},
52	:{'name':"Ignition Ctrl 1"},
53	:{'name':"Ignition Ctrl 2"},
54	:{'name':"Seat Control #1"},
55	:{'name':"Lighting Ctrl"},
56	:{'name':"Rear Steering "},
57	:{'name':"Water Pump"},
58	:{'name':"Climate Control 2"},
59	:{'name':"Trans. Display 1"},
60	:{'name':"Trans. Display 2"},
61	:{'name':"Emission Ctrl."},
62	:{'name':"Dynamic Stability"},
63	:{'name':"Oil Sensor"},
64	:{'name':"Suspension 2"},
65	:{'name':"Info. Ctrl 1"},
66	:{'name':"Ramp Control"},
67	:{'name':"Clutch/Converter"},
68	:{'name':"Aux. Heater #1"},
69	:{'name':"Aux. Heater #2"},
70	:{'name':"Engine Valver"},
71	:{'name':"Chassis Ctrl #1"},
72	:{'name':"Chassis Ctrl #2"},
73	:{'name':"Battery Charger"},
74	:{'name':"Comms, Cellular"},
75	:{'name':"Comms, Satellite"},
76	:{'name':"Comms, Radio"},
77	:{'name':"Steering Column"},
78	:{'name':"Fan Drive Ctrl"},
79	:{'name':"Seat Control #2"},
80	:{'name':"Parking Brake Ctrl"},
81	:{'name':"Aftertreatment #1 in"},
82	:{'name':"Aftertreatment #1 out"},
83	:{'name':"Safety Restraint 1"},
84	:{'name':"Cab Display #2"},
85	:{'name':"DPF Controller"},
86	:{'name':"Aftertreatment #2 in"},
87	:{'name':"Aftertreatment #2 out"},
88	:{'name':"Safety Restraint 2"},
89	:{'name':"Atmospheric Sensor"},
90	:{'name':"Powertrain Control"},
91	:{'name':"Power Manager"},
92	:{'name':"Engine Injection"},
93	:{'name':"Fire Protection"},
94	:{'name':"Driver Impairment"},
95	:{'name':"Supply Eq. Comms."},
96	:{'name':"Vehicle Comms."},
97	:{'name':"Fuel Cell System"},
129 :{'name':"Depth Sensor"},
241 :{'name':"Radio Interface"},
243 :{'name':"Marine Display 2"},
248	:{'name':"File Server"},
249	:{'name':"Service Tool #1"},
250	:{'name':"Service Tool #2"},
251	:{'name':"Data Logger"},
252	:{'name':"Experimental Use"},
253	:{'name':"Reserved for OEM"},
254	:{'name':"Null Address"},
255	:{'name':"GLOBAL"}
}
def get_sa_name(sa):
    try:
        return j1939_SA[sa]['name']
    except KeyError:
        return "Unknown"
    
# Define the queues
raw_data_queue = queue.Queue(5000)
processed_data_queue = queue.Queue(5000)
summary_data_queue = queue.Queue(2) # this is a holding queue for data. 
nav_data_queue = queue.Queue(5) # this is a holding queue for data.

# Setup CAN interfaces (adjust the settings according to your hardware)
#can_interfaces = ['can0', 'can1']
can_interfaces = ['can1']
can_bitrates = [250000,]

summary_data = {"total_count":0}
for i in can_interfaces:
    summary_data[i] = { "name":f"{i}",
                        "count":0,
                        "source":{}
                       }
          
                

# Control flags for logging
logging_active = threading.Event()

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='app.py %(levelname)s:%(message)s')
logger = logging.getLogger()

UPDATE_PERIOD = 0.91  # seconds
STATS_UPDATE_PERIOD = 0.29
BALLAST_UPDATE_TIME = 0.37
NAV_BROADCAST_PERIOD = 0.23

# Struct format for CAN frame
can_frame_format = "<lB3x8s"

# J1939 bit masks and shifts
PRIORITY_MASK = 0x1C000000
EDP_MASK = 0x02000000
DP_MASK = 0x01000000
PF_MASK = 0x00FF0000
PS_MASK = 0x0000FF00
SA_MASK = 0x000000FF
PDU1_PGN_MASK = 0x03FF0000
PDU2_PGN_MASK = 0x03FFFF00

def read_can_data(interface):
    # Create a raw socket and bind it to the CAN interface
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind((interface,))
    logger.info(f"Listening on {interface}: {sock.getsockname()}")
    while True:
        try:
            can_packet = sock.recv(16)
        except OSError as e:
            logger.info(f"Reading {interface} failed with error {e}")
            time.sleep(1)
            sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            sock.bind((interface,))
            continue

        can_time = time.time()
        extended_frame,can_id, can_dlc, can_data, can_id_string = unpack_CAN(can_packet)
        can_data_string = " ".join(["{:02X}".format(b) for b in can_data[:can_dlc]])
        if extended_frame:
            priority, pgn, da, sa = get_j1939_from_id(can_id)
        else:
            #11-bit IDs, so J1939 is not defined
            priority = 0xE #out of range value
            pgn = 0xFFFFE #made up no-sensical value
            da = 0xFE #null
            sa = 0xFE #null
        try:
            raw_data_queue.put((interface, sa, pgn, can_time, da, can_id_string, can_data_string, can_data[:can_dlc]))
            logger.debug(f"Raw data put in queue: {interface} {sa} {pgn} {can_time} {da} {can_id_string} {can_data_string}")
            summary_data['total_count']+=1
            summary_data[interface]['count']+=1
        except Exception as e:
            logger.warning(f"Failed to put data in raw_data_queue: {str(e)}")

def get_j1939_from_id(can_id):
    priority = (PRIORITY_MASK & can_id) >> 26
    PF = (can_id & PF_MASK) >> 16
    if PF >= 0xF0:  # PDU 2 format
        DA = 255
        PGN = (can_id & PDU2_PGN_MASK) >> 8
    else:  # PDU 1 format
        PGN = (can_id & PDU1_PGN_MASK) >> 8
        DA = (can_id & PS_MASK) >> 8
    SA = (can_id & SA_MASK)
    return priority, PGN, DA, SA

def unpack_CAN(can_packet):
    can_id, can_dlc, can_data = struct.unpack(can_frame_format, can_packet)
    extended_frame = bool(can_id & socket.CAN_EFF_FLAG)
    if extended_frame:
        can_id &= socket.CAN_EFF_MASK
        can_id_string = "{:08X}".format(can_id)
    else:  # Standard Frame
        can_id &= socket.CAN_SFF_MASK
        can_id_string = "{:03X}".format(can_id)
    return extended_frame,can_id, can_dlc, can_data, can_id_string

def autopilot():
    """
    This function is a placeholder for autopilot functionality.
    It can be extended to include logic for controlling the vessel's autopilot.
    """
    while True:
        # Placeholder for autopilot logic
        time.sleep(1)  # Simulate some processing delay

def process_data():
    start_time = time.time()
    ballast_start_time = time.time()
    nav_start_time = time.time()
    
    ballast_data = {}   
    nav_state = {
        "rudder":   None,   # degrees (+starboard, –port)
        "speed":    None,   # knots
        "hdg_goal": None,   # degrees True
        "heading":  None,   # degrees True
        "steer":    None,   # helm angle or rate‑of‑turn
        "steer_goal": None  # desired helm / ROT
    }
    while True:
        #while not raw_data_queue.empty():
            (interface, sa, pgn, can_time, da, can_id_string, can_data_string, can_data) = raw_data_queue.get()
            processed_data_queue.put((interface, sa, pgn, can_time, da, can_id_string, can_data_string, can_data))
            logger.debug(f"Received queue: {interface} {sa} {pgn} {can_time} {da} {can_id_string} {can_data_string}")
            try:
                summary_data[interface]["source"][sa]['count'] += 1
            except KeyError:
                summary_data[interface]["source"][sa] = {'count': 1, 'address': sa, 'name': get_sa_name(sa), 'pgns': {}}
            try:
                summary_data[interface]["source"][sa]['pgns'][pgn]['count'] += 1
            except KeyError:
                summary_data[interface]["source"][sa]['pgns'][pgn] = {'count': 1,'sums':[0,0,0,0,0,0,0,0],'sumsquared':[0,0,0,0,0,0,0,0] }  
            try:
                summary_data[interface]["source"][sa]['pgns'][pgn]['time_delta'] = "{:d}ms".format(
                    int((can_time - summary_data[interface]["source"][sa]['pgns'][pgn]['time']) * 1000))
            except KeyError:
                summary_data[interface]["source"][sa]['pgns'][pgn]['time_delta'] = "-1ms"

            summary_data[interface]["source"][sa]['pgns'][pgn]['time'] = can_time
            summary_data[interface]["source"][sa]['pgns'][pgn]['id'] = can_id_string
            summary_data[interface]["source"][sa]['pgns'][pgn]['da'] = da
            summary_data[interface]["source"][sa]['pgns'][pgn]['data'] = can_data_string
            
            for i in range(len(can_data)):
                summary_data[interface]["source"][sa]['pgns'][pgn]['sums'][i] += can_data[i]
                summary_data[interface]["source"][sa]['pgns'][pgn]['sumsquared'][i] += can_data[i]**2
            
            if logging_active.is_set():
                summary_data['logging'] = True
            else:
                summary_data['logging'] = False

            if (can_time - start_time) > STATS_UPDATE_PERIOD:
                start_time = can_time
                #socketio.emit('message', summary_data)  # Emit processed data to the WebSocket
                logger.debug(f"emitted message: {summary_data}")

            # Water level indicator added to the ballast pump lead tubes.
            if sa == 57 and pgn == 0x1F211: # Matches arduino script
                ballast_data["center_fill"]=bool(can_data[0])
                ballast_data["port_fill"]=bool(can_data[1])
                ballast_data["star_fill"]=bool(can_data[2])

            elif pgn == 127245 and len(can_data) >= 2:          # Rudder Angle
                angle = struct.unpack_from('<h', can_data)[0] * 0.0001 * 180/3.14159
                nav_state["rudder"] = round(angle, 1)

            elif pgn == 128259 and len(can_data) >= 2:          # Speed through water
                spd = struct.unpack_from('<H', can_data)[0] * 0.01 * 1.94384  # m/s → kn
                nav_state["speed"] = round(spd, 2)

            elif pgn == 127237 and len(can_data) >= 2:          # Heading/Track control (goal)
                goal = struct.unpack_from('<H', can_data)[0] * 0.0001 * 180/3.14159
                nav_state["hdg_goal"] = round(goal, 1)

            elif pgn == 127250 and len(can_data) >= 2:          # Actual vessel heading
                hdg = struct.unpack_from('<H', can_data)[0] * 0.0001 * 180/3.14159
                nav_state["heading"] = round(hdg, 1)

            elif pgn == 61469 and len(can_data) >= 8:          # Steering angle (2nd field)
                steer = (struct.unpack('<L', can_data[:4])[0] - 0x80000000)/1000
                nav_state["steer"] = round(steer)
                sgoal = (struct.unpack('<L', can_data[4:])[0] - 0x80000000)/1000
                nav_state["steer_goal"] = round(sgoal)
                nav_data_queue.put(nav_state)  # Add nav_state to the queue for later processing


            if (can_time - ballast_start_time) > BALLAST_UPDATE_TIME:
                ballast_start_time = can_time
                #socketio.emit('ballast', ballast_data)  # Emit processed data to the WebSocket
                logger.info(f"ballast: {ballast_data}")
                ballast_data={"center_fill": None,
                              "port_fill": None,
                              "star_fill": None}
                
            if (can_time - nav_start_time) > NAV_BROADCAST_PERIOD:
                nav_start_time = can_time
                #socketio.emit('nav_update', nav_state)
                logger.info(f"nav_update: {nav_state}")
                nav_state = {
                    "rudder":   None,   # degrees (+starboard, –port)
                    "speed":    None,   # knots
                    "hdg_goal": None,   # degrees True
                    "heading":  None,   # degrees True
                    "steer":    None,   # helm angle or rate‑of‑turn
                    "steer_goal": None  # desired helm / ROT
                }

            time.sleep(.005)

def socket_can_data(interface):
    while True:
        data = get_can_stats(interface)
        socketio.emit('can_stats', data)  # Emit processed data to the WebSocket
        #logger.debug(f"emitted can_stats: {data}")
        time.sleep(1.09)

def write_to_db(table_name):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    interface TEXT,
                    sa INTEGER,
                    pgn INTEGER,
                    timestamp FLOAT,
                    da INTEGER,
                    can_id TEXT,
                    data_hex TEXT,
                    data_bytes BLOB,
                    PRIMARY KEY (interface, sa, pgn, timestamp)
                )
            ''')
    conn.commit()
    cursor.close()
    while True:
        table_data = []
        time.sleep(UPDATE_PERIOD)
        while not processed_data_queue.empty():
            #data = (interface, sa, pgn, can_time, da, can_id, can_data_string, can_data)
            data = processed_data_queue.get() 
            table_data.append(data)
        if logging_active.is_set():  # check to see if logging is active    
            try:
                conn = sqlite3.connect(DATABASE)
                with conn:
                    conn.executemany(f'''
                        INSERT INTO {table_name} (interface, sa, pgn, timestamp, da, can_id, data_hex, data_bytes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', table_data)
                    #logger.debug(f"Inserted {len(table_data)} lines into the database.")
            except sqlite3.Error as e:
                logger.warning(f"SQLite transaction error: {e}")
            except Exception as e:
                logger.warning(f"Database error: {e}")
            finally:
                conn.close()
    

################################################
# Pages
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ballast_control')
def ballast_control():
    return render_template('ballast_control.html')

@app.route('/j1939_display')
def j1939_display():
    return render_template('j1939_display.html', server_ip=get_ip_address())

@app.route('/remote_rudder')
def remote_rudder():
    return render_template('remote_rudder.html')

@app.route('/address_claim')
def address_claim():
    return render_template('address_claim.html')

@app.route('/utility')
def utility():
    return render_template('utility.html')

############################################
# API calls

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/tables', methods=['GET'])
def get_tables():
    # Connect to the SQLite database
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Execute the query to get the list of tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    
    # Fetch all results
    tables = cursor.fetchall()
    
    non_zero_tables = {}
    
    # Check the row count of each table
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        if count > 0:
            non_zero_tables[table_name] = count
    
    # Close the connection
    conn.close()
    
    return jsonify(non_zero_tables)
    
        
def is_valid_hex(can_id):
    # Check if the string contains only valid hex characters
    return bool(re.fullmatch(r'[0-9A-Fa-f]+', can_id))

@app.route('/api/messages', methods=['GET'])
def get_messages():
    conn = get_db()
    cursor = conn.cursor()
    
    table_name = request.args.get('table_name')
    can_ids = request.args.getlist('can_id')
    
    if not table_name:
        return jsonify({"error": "table_name parameter is required"}), 400
    if not can_ids:
        return jsonify({"error": "can_id parameter is required"}), 400
    
    # Validate can_id values
    for can_id in can_ids:
        if not is_valid_hex(can_id):
            return jsonify({"error": f"Invalid can_id value: {can_id}"}), 400
    
    try:
        query = f"SELECT * FROM {table_name} WHERE can_id IN ({','.join('?' for _ in can_ids)})"
        cursor.execute(query, can_ids)
        rows = cursor.fetchall()
        messages = [dict(row) for row in rows]
        return jsonify(messages)
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/delete_table', methods=['POST'])
def delete_table():
    logger.info("Delete table data has been requested.")
    post_data = request.get_json()
    logger.info(post_data)
    try:
        table_name = post_data['table_name']
    except KeyError as e:
        return jsonify({"error": "table_name key was not in the post data."}), 400
    
    if not table_name:
        return jsonify({"error": "table_name parameter is required"}), 400
    
    try:
        #connect to the database
        conn = get_db()
        cursor = conn.cursor()
    
        query = f"DELETE FROM {table_name}"
        cursor.execute(query)
        conn.commit()
        cursor.execute("VACUUM")
        conn.commit()
        
    except sqlite3.Error as e:
        return jsonify({"success":False, "error": str(e)}), 500    
    except Exception as e:
        return jsonify({"success":False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
    logger.info(f"Table {table_name} deleted successfully")
    return jsonify({"success":True, "message": f"Table {table_name} deleted successfully"}), 200

@app.route('/api/download_db', methods=['POST'])
def download_db():
    return send_file(DATABASE, 
                     as_attachment=True,
                     download_name=f'{DATABASE}')

def generate_csv( table_name, chunk_size=100000):
    # Connect to the SQLite database
    conn =  get_db()
    cursor = conn.cursor()

    # Get column headers
    cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
    headers = [description[0] for description in cursor.description]

    # Create a CSV writer that writes to an in-memory list
    yield ','.join(headers) + '\n'  # Write header row

    offset = 0
    while True:
        # Fetch a chunk of rows
        cursor.execute(f"SELECT * FROM {table_name} LIMIT {chunk_size} OFFSET {offset}")
        rows = cursor.fetchall()
        if not rows:
            break

        # Write rows to CSV format and yield each row
        for row in rows:
            yield ','.join(map(str, row)) + '\n'

        # Move to the next chunk
        offset += chunk_size

    # Close the database connection
    conn.close()

@app.route('/api/download', methods=['POST'])
def download_table():
    table_name = request.form['table_name']
    if not table_name:
        return jsonify({"error": "table_name parameter is required"}), 400

    # Stream the CSV to the browser
    response = Response(generate_csv(table_name), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="can_data_output.csv")
    return response

def get_ip_address():
    ip_addresses = {}
    for interface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address != '127.0.0.1':
                ip_addresses[interface] = addr.address
                return addr.address
 
@app.route('/api/ip', methods=['GET'])
def get_ip():
    ip_address = get_ip_address()
    return jsonify({'ip': ip_address})


def get_can_stats(interface):
    # Command to get CAN statistics with detailed information
    command = f"ip -details -statistics link show {interface}"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": "Failed to retrieve CAN statistics"}
    
    # Parsing the result
    stats = {}
    stat_lines = result.stdout.split('\n')
    for line in range(len(stat_lines)):
        if 'can state' in stat_lines[line]:
            stats['CANstate'] = stat_lines[line].strip().split()[2]
            if "ERROR" in stats['CANstate']:
                stats['CANstate'] = stats['CANstate'].split('-')[-1]
        elif 'bitrate' in stat_lines[line]:
            bitrate = int(stat_lines[line].strip().split()[1])//1000
            stats['CANbitrate'] = f"{bitrate}k"
        elif 'RX:' in stat_lines[line]:
            rx_header = stat_lines[line].strip().split()[1:] #Remove the "RX:"
            rx_line = stat_lines[line+1].strip().split()
            for k,v in zip(rx_header,rx_line):
                stats['CANRX'+k] = f"{int(v)//1024}kB"
        elif 'TX:' in stat_lines[line]:
            tx_header = stat_lines[line].strip().split()[1:] #Remove the "TX:"
            tx_line = stat_lines[line+1].strip().split()
            for k,v in zip(tx_header,tx_line):
                stats['CANTX'+k] = v
    return {interface:stats}

@app.route('/api/can_stats', methods=['GET'])
def can_stats():
    stats = get_can_stats(interface)
    return jsonify(stats)

def start_can(bitrate,interface='can0'):
    '''
    For this function to work, we need to run `sudo visudo` and add the following lines:
    your_username ALL=(ALL) NOPASSWD: /sbin/ip link set can0 up type can bitrate

    '''
    stop_can()
    
    try:
        command = f"sudo ip link set {interface} up type can bitrate {bitrate} restart-ms 100"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return {"status": "error", "output": result.stderr}
        else:
            return {"status": "success", "output": command}
    except subprocess.CalledProcessError:
        return {"status": "error", "output": result.stderr}

@app.route('/api/start_can', methods=['POST'])
def set_bitrate(interface='can0'):
    bitrate = request.form.get('bitrate')
    try:
        if int(bitrate) not in [250000, 500000, 125000, 1000000, 666666, 666000]:
            bitrate = 250000
        result = start_can(bitrate, interface)
        return jsonify({'message':result, 'bitrate':bitrate})
    except ValueError:
        jsonify({"status": "error", "message": "Improper bitrate specified"}), 400

@app.route('/api/stop_can', methods=['GET'])
def stop_can(interface='can0'):
    try:
        command = f"sudo ip link set {interface} down"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode !=0:
            return jsonify({"status": "error", "output": result.stderr})
        else:
            return jsonify({"status": "success", "message": f"Executed Command: {command}"})
    except subprocess.CalledProcessError:
        return jsonify({"status": "error", "output": result.stderr})

@app.route('/api/shutdown', methods=['GET'])
def system_shutdown():
    try:
        command = "sudo shutdown -h now"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode !=0:
            return jsonify({"status": "error", "output": result.stderr})
        else:
            return jsonify({"status": "success", "output":result.stdout, "message": f"Executed Command: {command}"})
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)})

@app.route('/start_logging', methods=['GET'])
def start_logging():
    logging_active.set()
    return jsonify({"status": "Logging started"}), 200

@app.route('/stop_logging', methods=['GET'])
def stop_logging():
    logging_active.clear()
    return jsonify({"status": "Logging stopped"}), 200

@app.route('/restart_logging', methods=['POST'])
def restart_logging():
    table_name = request.json.get('table_name')
    if not table_name:
        return jsonify({"error": "Table name is required"}), 400
    
    logging_active.clear()
    global write_thread
    write_thread = threading.Thread(target=write_to_db, args=(table_name,))
    write_thread.daemon = True
    write_thread.start()
    logging_active.set()
    return jsonify({"status": f"Logging restarted with table {table_name}"}), 200

@app.route('/drop_table', methods=['POST'])
def drop_table():
    table_name = request.json.get('table_name')
    if not table_name:
        return jsonify({"error": "Table name is required"}), 400
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.commit()
    conn.close()
    return jsonify({"status": f"Table {table_name} dropped"}), 200



if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=5000, debug=False)
    # Define the threads for reading CAN data
    logger.info(f"Setting up read and information threads for {can_interfaces}")
    read_threads = []
    info_threads = []
    for interface in can_interfaces:
        t = threading.Thread(target=read_can_data, args=(interface,))
        info = threading.Thread(target=socket_can_data, args=(interface,))
        t.daemon = True
        info.daemon = True
        read_threads.append(t)
        info_threads.append(info)
        t.start()
        info.start()
    logger.info(f"Started {len(read_threads)} read threads and {len(info_threads)} info threads.")

    logger.info(f"Setting up data processing thread.")
    # Thread for processing data
    process_thread = threading.Thread(target=process_data)
    process_thread.daemon = True
    process_thread.start()

    # # Thread for processing data
    # autopilot_thread = threading.Thread(target=autopilot)
    # autopilot_thread.daemon = True
    # autopilot_thread.start()

    # Thread for writing data to SQLite
    logger.info(f"Starting database writing thread.")
    write_thread = threading.Thread(target=write_to_db, args=("can_data",))
    write_thread.daemon = True
    write_thread.start()
    
    logger.info("Running flask app on port 5000")
    # Run Flask app with SocketIO
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")


