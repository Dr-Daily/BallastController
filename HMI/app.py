#!/python
from flask import Flask, jsonify,render_template, request, send_file
import csv
import io
import subprocess
import humanize #sudo apt install python3-humanize
#from flask_cors import CORS
import psutil
import socket
import sqlite3
import re
import time

DATABASE = 'can_messages.db'

app = Flask(__name__)
#CORS(app)

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

def get_j1939_sa(sa):
    try:
        return j1939_SA[sa]['name']
    except:
        return "Unknown"

def is_valid_table_name(table_name):
    # Only allow alphanumeric characters and underscores
    return re.match(r'^[a-zA-Z0-9_]+$', table_name) is not None

# After making changes, run 
# sudo systemctl restart flask-app.service
# to restart.

# To debug, run 
# sudo systemctl status flask-app.service
#
# If that's not enough, run
# journalctl -r 
# to get the tail end of the system journal


################################################
# Pages
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ballast_control')
def ballast_control():
    return render_template('ballast_control.html', server_ip=get_ip_address())

@app.route('/j1939_display')
def j1939_display():
    return render_template('j1939_display.html', server_ip=get_ip_address())

@app.route('/remote_rudder')
def remote_rudder():
    return render_template('remote_rudder.html', server_ip=get_ip_address())

@app.route('/test')
def test():
    return render_template('can_websocket_test.html', server_ip=get_ip_address())


############################################
# API calls

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# @app.route('/api/tables', methods=['GET'])
# def get_tables():
#     try:
#         conn = get_db()
#         cursor = conn.cursor()
        
#         # Query the SQLite schema to get the list of tables
#         cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
#         rows = cursor.fetchall()
        
#         # Extract the table names from the query result
#         tables = [row['name'] for row in rows]
        
#         # Close the database connection
#         cursor.close()
#         conn.close()
        
#         # Return the result as JSON
#         return jsonify({"status": "success", "tables": tables})
    
#     except Exception as e:
#         return jsonify({"status": "error", "output": str(e)})
        
def is_valid_hex(can_id):
    # Check if the string contains only valid hex characters
    return bool(re.fullmatch(r'[0-9A-Fa-f]+', can_id))

# @app.route('/api/messages', methods=['GET'])
# def get_messages():
#     conn = get_db()
#     cursor = conn.cursor()
    
#     table_name = request.args.get('table_name')
#     can_ids = request.args.getlist('can_id')
    
#     if not table_name:
#         return jsonify({"error": "table_name parameter is required"}), 400
#     if not can_ids:
#         return jsonify({"error": "can_id parameter is required"}), 400
    
#     # Validate can_id values
#     for can_id in can_ids:
#         if not is_valid_hex(can_id):
#             return jsonify({"error": f"Invalid can_id value: {can_id}"}), 400
    
#     try:
#         query = f"SELECT * FROM {table_name} WHERE can_id IN ({','.join('?' for _ in can_ids)})"
#         cursor.execute(query, can_ids)
#         rows = cursor.fetchall()
#         messages = [dict(row) for row in rows]
#         return jsonify(messages)
#     except sqlite3.Error as e:
#         return jsonify({"error": str(e)}), 500
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500
#     finally:
#         cursor.close()
#         conn.close()

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


# @app.route('/api/download', methods=['GET'])
# def download_table():
    
#     table_name = request.args.get('table_name')
    
#     if not table_name:
#         return jsonify({"error": "table_name parameter is required"}), 400
    
#     try:
#         #connect to the database
#         conn = get_db()
#         cursor = conn.cursor()
    
#         query = f"SELECT * FROM {table_name}"
#         cursor.execute(query)
#         rows = cursor.fetchall()

#         # Get column names
#         column_names = [description[0] for description in cursor.description]

#         # Create a CSV file in memory
#         output = io.StringIO()
#         writer = csv.writer(output)
#         writer.writerow(column_names)  # write the header
#         writer.writerows(rows)

#         # Set the CSV file's pointer to the beginning
#         output.seek(0)

#         # Serve the CSV file
#         return send_file(
#             io.BytesIO(output.getvalue().encode()),
#             mimetype='text/csv',
#             as_attachment=True,
#             download_name=f'{table_name}.csv'
#         )
    
#     except sqlite3.Error as e:
#         return jsonify({"error": str(e)}), 500    
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500
#     finally:
#         cursor.close()
#         conn.close()

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


# def get_can_stats():
#     # Command to get CAN statistics with detailed information
#     command = "ip -details -statistics link show can0"
#     result = subprocess.run(command, shell=True, capture_output=True, text=True)
#     if result.returncode != 0:
#         return {"error": "Failed to retrieve CAN statistics"}
    
#     # Parsing the result
#     stats = {}
#     stat_lines = result.stdout.split('\n')
#     for line in range(len(stat_lines)):
#         if 'can state' in stat_lines[line]:
#             stats['CANstate'] = stat_lines[line].strip().split()[2]
#             if "ERROR" in stats['CANstate']:
#                 stats['CANstate'] = stats['CANstate'].split('-')[-1]
#         elif 'bitrate' in stat_lines[line]:
#             bitrate = int(stat_lines[line].strip().split()[1])//1000
#             stats['CANbitrate'] = f"{bitrate}k"
#         elif 'RX:' in stat_lines[line]:
#             rx_header = stat_lines[line].strip().split()[1:] #Remove the "RX:"
#             rx_line = stat_lines[line+1].strip().split()
#             for k,v in zip(rx_header,rx_line):
#                 stats['CANRX'+k] = humanize.naturalsize(int(v), binary=True)
#         elif 'TX:' in stat_lines[line]:
#             tx_header = stat_lines[line].strip().split()[1:] #Remove the "TX:"
#             tx_line = stat_lines[line+1].strip().split()
#             for k,v in zip(tx_header,tx_line):
#                 stats['CANTX'+k] = v
#     return stats

# @app.route('/api/can_stats', methods=['GET'])
# def can_stats():
#     stats = get_can_stats()
#     return jsonify(stats)

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

# @app.route('/api/source_addresses', methods=['GET'])
# def get_source_addresses():
#     table_name = request.args.get('table_name')
#     if not table_name:
#         return jsonify({"status": "error", "output": "table_name parameter is required"}), 400
#     if not is_valid_table_name(table_name):
#         return jsonify({"status": "error", "output": "Invalid table_name parameter"}), 400
    
#     try:
#         # Connect to the SQLite database
#         conn = sqlite3.connect(DATABASE)
#         cursor = conn.cursor()
        
#          # Execute the query to get all unique source addresses and their counts
#         cursor.execute(f"SELECT sa, COUNT(sa) as count FROM {table_name} GROUP BY sa")
#         rows = cursor.fetchall()
        
#         # Extract the source addresses and their counts from the query result
#         source_addresses = [{"sa": row[0], "name":get_j1939_sa(row[0]), "count": row[1]} for row in rows]
        
#         # Close the database connection
#         cursor.close()
#         conn.close()
        
#         # Return the result as JSON
#         return jsonify({"status": "success", "source_addresses": source_addresses})

#     except Exception as e:
#         return jsonify({"status": "error", "output": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


