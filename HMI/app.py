#!/python
from flask import Flask, jsonify,render_template, request, send_file
import csv
import io
import subprocess
import humanize #sudo apt install python3-humanize
from flask_cors import CORS
import psutil
import socket
import sqlite3
import re
import time

DATABASE = 'can_messages.db'

app = Flask(__name__)
CORS(app)

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


def get_can_stats():
    # Command to get CAN statistics with detailed information
    command = "ip -details -statistics link show can0"
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
                stats['CANRX'+k] = humanize.naturalsize(int(v), binary=True)
        elif 'TX:' in stat_lines[line]:
            tx_header = stat_lines[line].strip().split()[1:] #Remove the "TX:"
            tx_line = stat_lines[line+1].strip().split()
            for k,v in zip(tx_header,tx_line):
                stats['CANTX'+k] = v
    return stats

@app.route('/api/can_stats', methods=['GET'])
def can_stats():
    stats = get_can_stats()
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)


