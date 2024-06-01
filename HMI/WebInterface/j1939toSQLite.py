import sqlite3
import struct
import socket
import time

# Define CAN frame format
can_frame_format = "<lB3x8s"

# Define database schema
create_table_sql = """
CREATE TABLE IF NOT EXISTS can_messages (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    can_id INTEGER,
    can_id_hex TEXT,
    priority INTEGER,
    pgn INTEGER,
    da INTEGER,
    sa INTEGER,
    can_dlc INTEGER,
    can_data TEXT,
    can_bytes BLOB
);
"""

# Function to unpack CAN packet
def unpack_CAN(can_packet):
    can_id, can_dlc, can_data = struct.unpack(can_frame_format, can_packet)
    #TODO: Get error messages 
    extended_frame = bool(can_id & socket.CAN_EFF_FLAG)
    if extended_frame:
        can_id &= socket.CAN_EFF_MASK
        can_id_string = "{:8X}".format(can_id)
    else:
        can_id &= socket.CAN_SFF_MASK
        can_id_string = "{:3X}".format(can_id)
    hex_data_string = ' '.join(["{:02X}".format(b) for b in can_data[:can_dlc]])
    return can_id, can_id_string, can_dlc, hex_data_string, can_data

# Function to initialize the database
def init_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(create_table_sql)
    conn.commit()
    return conn

# Function to insert CAN message into the database
def insert_can_message(conn, timestamp,can_id,can_id_hex,priority,pgn,da,sa,can_dlc,can_data,can_bytes):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO can_messages (timestamp,can_id,can_id_hex,priority,pgn,da,sa,can_dlc,can_data) VALUES (?,?,?,?,?,?,?,?,?)",
        (timestamp,can_id,can_id_hex,priority,pgn,da,sa,can_dlc,can_data, can_bytes)
    )
    conn.commit()

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

# Main function to read CAN messages and store them in the database
def main(interface, db_path):
    # Initialize the database
    conn = init_db(db_path)

    # Open a socket and bind to it from SocketCAN
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind((interface,))

    print(f"Listening on {interface} and storing messages to {db_path}")

    try:
        while True:
            # Read the message from the network
            can_packet = sock.recv(16)
            timestamp = time.time()

            # Parse the CAN message
            can_id, can_id_hex, can_dlc, can_data, can_bytes = unpack_CAN(can_packet)
            priority,pgn,da,sa = get_j1939_from_id(can_id)

            # Insert the message into the database
            insert_can_message(conn, timestamp,can_id,can_id_hex,priority,pgn,da,sa,can_dlc,can_data,can_bytes)
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        conn.close()
        print("Connection closed and program terminated")

if __name__ == "__main__":
    # Change these as needed
    interface = "can0"
    db_path = "j1939Messages.db"
    main(interface, db_path)
