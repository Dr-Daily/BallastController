from flask import Flask, jsonify
from flask_cors import CORS
import socket

app = Flask(__name__)
CORS(app)

def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        ip_address = s.getsockname()[0]
    except Exception:
        ip_address = '127.0.0.1'
    finally:
        s.close()
    return ip_address

@app.route('/api/ip', methods=['GET'])
def get_ip():
    ip_address = get_ip_address()
    return jsonify({'ip': ip_address})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
