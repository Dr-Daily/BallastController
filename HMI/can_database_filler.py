import time
import socket
import struct
import sqlite3
import logging
from datetime import datetime
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO, format='can_db_filler %(levelname)s:%(message)s')
logger = logging.getLogger()

UPDATE_PERIOD = 0.91  # seconds
CAN_INTERFACE = 'can0'
CAN_BITRATE = 250000

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
    return can_id, can_dlc, can_data, can_id_string


def collect_data(cursor, table_name, meta_data_table_name):
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind((CAN_INTERFACE,))

    data = {"Source": {}}
    table_data = []
    start_time = time.time()
    last_loop_time = 0
    while True:
        try:
            can_packet = sock.recv(16)
        except OSError as e:
            logger.info(f"Reading {CAN_INTERFACE} failed with error {e}")
            time.sleep(1)
            sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            sock.bind((CAN_INTERFACE,))
            continue

        can_time = time.time()
        loop_time = int((can_time - last_loop_time) * 1000000)
        last_loop_time = can_time

        can_id, can_dlc, can_data, can_id_string = unpack_CAN(can_packet)
        can_data_string = " ".join(["{:02X}".format(b) for b in can_data])
        priority, pgn, da, sa = get_j1939_from_id(can_id)

        if sa in data["Source"]:
            data["Source"][sa]['count'] += 1
        else:
            data["Source"][sa] = {'count': 1, 'address': sa, 'pgns': {}}

        if pgn in data["Source"][sa]['pgns']:
            data["Source"][sa]['pgns'][pgn]['count'] += 1
            data["Source"][sa]['pgns'][pgn]['time_delta'] = "{:d}ms".format(
                int((can_time - data["Source"][sa]['pgns'][pgn]['time']) * 1000))
        else:
            data["Source"][sa]['pgns'][pgn] = {'count': 1, 'time_delta': 0}

        data["Source"][sa]['pgns'][pgn]['time'] = can_time
        data["Source"][sa]['pgns'][pgn]['id'] = can_id_string
        data["Source"][sa]['pgns'][pgn]['da'] = da
        data["Source"][sa]['pgns'][pgn]['data'] = can_data_string

        table_data.append((CAN_INTERFACE, sa, pgn, can_time, da, can_id, can_data_string, can_data))

        if (can_time - start_time) > UPDATE_PERIOD:
            start_time = time.time()
            try:
                cursor.execute('BEGIN;')
                for item in table_data:
                    cursor.execute(f'''
                        INSERT INTO {table_name} (interface, sa, pgn, timestamp, da, can_id, data_hex, data_bytes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', item)
                cursor.execute(f'''
                    UPDATE {meta_data_table_name}
                    SET num_messages = ?
                    WHERE table_name = ?
                ''', (len(table_data), table_name))
                cursor.execute('COMMIT;')
            except sqlite3.Error as e:
                cursor.execute('ROLLBACK;')
                logger.warning(f"SQLite transaction error: {e}")
            finally:
                table_data = []


if __name__ == "__main__":
    try:
        command = f"sudo ip link set {CAN_INTERFACE} down"
        subprocess.run(command, shell=True, capture_output=True, text=True)
        command = f"sudo ip link set {CAN_INTERFACE} up type can bitrate {CAN_BITRATE} restart-ms 100"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(result.stderr)
    except Exception as e:
        logger.error(str(e))

    while True:
        logger.info("Starting CAN Server with SQLite")

        conn = sqlite3.connect('can_messages.db')
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA cache_size=8000;')
        cursor = conn.cursor()

        table_sizes = {}

        table_name = f'{datetime.now().strftime("J1939_%Y%m%d_%H%M%S")}'
        meta_data_table_name = table_name + "_meta"
        table_sizes[table_name] = 0
        try:
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
            cursor.execute(f'''
                CREATE INDEX idx_pgn
                ON {table_name} (pgn)
            ''')
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {meta_data_table_name} (
                    interface TEXT,
                    sa INTEGER,
                    pgn INTEGER,
                    da INTEGER,
                    can_id TEXT,
                    count INTEGER,
                    period FLOAT,
                    b0mean FLOAT,
                    b0std FLOAT,
                    b1mean FLOAT,
                    b1std FLOAT,
                    b2mean FLOAT,
                    b2std FLOAT,
                    b3mean FLOAT,
                    b3std FLOAT,
                    b4mean FLOAT,
                    b4std FLOAT,
                    b5mean FLOAT,
                    b5std FLOAT,
                    b6mean FLOAT,
                    b6std FLOAT,
                    b7mean FLOAT,
                    b7std FLOAT,
                    PRIMARY KEY (interface, sa, pgn, da)
                )
            ''')
            cursor.execute(f'''
                CREATE INDEX idx_pgn
                ON {meta_data_table_name} (pgn)
            ''')
            conn.commit()
            logger.info(f"Created Table {table_name} in database.")
        except sqlite3.Error as e:
            logger.error(str(e))
            time.sleep(5)
        except Exception as e:
            logger.warning(repr(e))

        collect_data(cursor, table_name, meta_data_table_name)

        cursor.close()
        conn.close()

        time.sleep(1)
