from flask import Flask, jsonify
from flask_cors import CORS
import psutil
import socket

app = Flask(__name__)
CORS(app)

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



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
