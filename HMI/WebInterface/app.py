from flask import Flask, jsonify,render_template
import subprocess
from flask_cors import CORS
import psutil
import socket

app = Flask(__name__)
CORS(app)


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
    return render_template('j1939_display.html')

@app.route('/remote_rudder')
def remote_rudder():
    return render_template('remote_rudder.html')


############################################
# API calls

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
    for line in result.stdout.split('\n'):
        if 'state' in line:
            stats['State'] = line.split()[-1]
        if 'bitrate' in line:
            stats['Bitrate'] = line.split()[-2]
        if 'RX:' in line:
            rx_line = line.split()
            stats['RX packets'] = rx_line[1]
            stats['RX errors'] = rx_line[2]
            stats['RX dropped'] = rx_line[3]
            stats['RX overruns'] = rx_line[4]
            stats['RX frame'] = rx_line[5]
        if 'TX:' in line:
            tx_line = line.split()
            stats['TX packets'] = tx_line[1]
            stats['TX errors'] = tx_line[2]
            stats['TX dropped'] = tx_line[3]
            stats['TX aborted'] = tx_line[4]
            stats['TX carrier'] = tx_line[5]
            stats['TX restart'] = tx_line[6]
    
    return stats

@app.route('/api/can_stats', methods=['GET'])
def can_stats():
    stats = get_can_stats()
    return jsonify(stats)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)


