#!/python
from flask import Flask, jsonify,render_template, request, send_file
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

DATABASE = 'can_messages.db'

app = Flask(__name__)
socketio = SocketIO(app,async_mode='threading', cors_allowed_origins="*")

# After making changes, run 
# sudo systemctl restart flask-app.service
# to restart.

# To debug, run 
# sudo systemctl status flask-app.service
#
# If that's not enough, run
# journalctl -r 
# to get the tail end of the system journal

# Define the queues
raw_data_queue = queue.Queue()
processed_data_queue = queue.Queue()
summary_data_queue = queue.Queue(2) # this is a holding queue for data. 

# Setup CAN interfaces (adjust the settings according to your hardware)
#can_interfaces = ['can0', 'can1']
can_interfaces = ['can0',]
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
logging.basicConfig(level=logging.INFO, format='app.py %(levelname)s:%(message)s')
logger = logging.getLogger()

UPDATE_PERIOD = 0.91  # seconds
STATS_UPDATE_PERIOD = 0.29

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

def process_data():
    
    sa_data = {"Source":{}}
    while True:
        while not raw_data_queue.empty():
            (interface, sa, pgn, can_time, da, can_id_string, can_data_string, can_data) = raw_data_queue.get()
            processed_data_queue.put((interface, sa, pgn, can_time, da, can_id_string, can_data_string, can_data))
        
            try:
                summary_data[interface]["source"][sa]['count'] += 1
                sa_data["Source"][sa]['count'] += 1
            except KeyError:
                summary_data[interface]["source"][sa] = {'count': 1, 'address': sa, 'pgns': {}}
                sa_data["Source"][sa] = {'count': 1, 'address': sa, 'pgns': {}}
            try:
                summary_data[interface]["source"][sa]['pgns'][pgn]['count'] += 1
            except KeyError:
                summary_data[interface]["source"][sa]['pgns'][pgn] = {'count': 1}
                
            summary_data[interface]["source"][sa]['pgns'][pgn]['time'] = can_time
            summary_data[interface]["source"][sa]['pgns'][pgn]['id'] = can_id_string
            summary_data[interface]["source"][sa]['pgns'][pgn]['da'] = da
            summary_data[interface]["source"][sa]['pgns'][pgn]['data'] = can_data_string
            summary_data[interface]["source"][sa]['pgns'][pgn]['time_delta'] = "{:d}ms".format(
                    int((can_time - summary_data[interface]["source"][sa]['pgns'][pgn]['time']) * 1000))
            
            
        socketio.emit('message', sa_data)  # Emit processed data to the WebSocket
        time.sleep(STATS_UPDATE_PERIOD)

def socket_can_data(interface):
    while True:
        data = get_can_stats(interface)
        socketio.emit('can_stats', data)  # Emit processed data to the WebSocket
        logger.debug(f"emitted can_stats: {data}")
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
    table_data = []
    while True:
        while not processed_data_queue.empty():
            data = processed_data_queue.get() 
            #data = (interface, sa, pgn, can_time, da, can_id, can_data_string, can_data)
            table_data.append(data)
        if logging_active.is_set():  # check to see if logging is active    
            try:
                cursor.execute('BEGIN;')
                for item in table_data:
                    cursor.execute(f'''
                        INSERT INTO {table_name} (interface, sa, pgn, timestamp, da, can_id, data_hex, data_bytes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', item)
                cursor.execute('COMMIT;')
            except sqlite3.Error as e:
                cursor.execute('ROLLBACK;')
                logger.warning(f"SQLite transaction error: {e}")
            logger.debug(f"Inserted {len(table_data)} lines into the database.")
            table_data = []
        time.sleep(UPDATE_PERIOD)
        


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

@app.route('/mqtt')
def mqtt():
    return render_template('mqtt.html')


############################################
# API calls

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/tables', methods=['GET'])
def get_tables():
    return
        
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

@app.route('/api/delete_table', methods=['GET'])
def delete_table():
    
    table_name = request.args.get('table_name')
    
    if not table_name:
        return jsonify({"error": "table_name parameter is required"}), 400
    
    try:
        #connect to the database
        conn = get_db()
        cursor = conn.cursor()
    
        query = f"DROP TABLE {table_name}"
        cursor.execute(query)
        conn.commit()
        return jsonify({"message": f"Table {table_name} deleted successfully"}), 200
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/download', methods=['GET'])
def download_table():
    
    table_name = request.args.get('table_name')
    
    if not table_name:
        return jsonify({"error": "table_name parameter is required"}), 400
    
    try:
        #connect to the database
        conn = get_db()
        cursor = conn.cursor()
    
        query = f"SELECT * FROM {table_name}"
        cursor.execute(query)
        rows = cursor.fetchall()

        # Get column names
        column_names = [description[0] for description in cursor.description]

        # Create a CSV file in memory
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(column_names)  # write the header
        writer.writerows(rows)

        # Set the CSV file's pointer to the beginning
        output.seek(0)

        # Serve the CSV file
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{table_name}.csv'
        )
    
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

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

def start_can(bitrate):
    '''
    For this function to work, we need to run `sudo visudo` and add the following lines:
    your_username ALL=(ALL) NOPASSWD: /sbin/ip link set can0 up type can bitrate

    '''
    stop_can()
    
    try:
        command = f"sudo ip link set can0 up type can bitrate {bitrate} restart-ms 100"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return {"status": "error", "output": result.stderr}
        else:
            return {"status": "success", "output": command}
    except subprocess.CalledProcessError:
        return {"status": "error", "output": result.stderr}

@app.route('/api/start_can', methods=['POST'])
def set_bitrate():
    bitrate = request.form.get('bitrate')
    try:
        if int(bitrate) not in [250000, 500000, 125000, 1000000, 666666, 666000]:
            bitrate = 250000
        result = start_can(bitrate)
        return jsonify({'message':result, 'bitrate':bitrate})
    except ValueError:
        jsonify({"status": "error", "message": "Improper bitrate specified"}), 400

@app.route('/api/stop_can', methods=['GET'])
def stop_can():
    try:
        command = "sudo ip link set can0 down"
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

@app.route('/start_logging', methods=['POST'])
def start_logging():
    logging_active.set()
    return jsonify({"status": "Logging started"}), 200

@app.route('/stop_logging', methods=['POST'])
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

    logger.info(f"Setting up data processing thread.")
    # Thread for processing data
    process_thread = threading.Thread(target=process_data)
    process_thread.daemon = True
    process_thread.start()

    # Thread for writing data to SQLite
    logger.info(f"Starting database writing thread.")
    write_thread = threading.Thread(target=write_to_db, args=("can_data",))
    write_thread.daemon = True
    write_thread.start()
    
    logger.info("Running flask app on port 5000")
    # Run Flask app with SocketIO
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True )

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")


