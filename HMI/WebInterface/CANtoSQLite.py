import sqlite3
import subprocess
import time
import re

# Define database schema
create_table_sql = """
CREATE TABLE IF NOT EXISTS can_messages (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    can_id TEXT,
    can_dlc INTEGER,
    can_data TEXT
);
"""

# Function to initialize the database
def init_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(create_table_sql)
    conn.commit()
    return conn

# Function to insert CAN message into the database
def insert_can_message(conn, timestamp, can_id, can_dlc, can_data):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO can_messages (timestamp, can_id, can_dlc, can_data) VALUES (?, ?, ?, ?)",
        (timestamp, can_id, can_dlc, can_data)
    )
    conn.commit()

# Function to parse a line from candump output
def parse_candump_line(line):
    match = re.match(r'^\((\d+\.\d+)\) (\S+) (\S+)\#(\S*)', line)
    if match:
        timestamp = float(match.group(1))
        can_id = match.group(2)
        can_dlc = len(match.group(4)) // 2  # Each byte is represented by two hex characters
        can_data = match.group(4)
        return timestamp, can_id, can_dlc, can_data
    return None

# Main function to capture and process CAN data
def main(interface, db_path):
    # Initialize the database
    conn = init_db(db_path)

    # Run candump command and capture the output
    candump_process = subprocess.Popen(
        ['candump', '-L', interface],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    print(f"Listening on {interface} and storing messages to {db_path}")

    try:
        while True:
            line = candump_process.stdout.readline()
            if line:
                parsed_data = parse_candump_line(line)
                if parsed_data:
                    timestamp, can_id, can_dlc, can_data = parsed_data
                    insert_can_message(conn, timestamp, can_id, can_dlc, can_data)
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        candump_process.terminate()
        conn.close()
        print("Connection closed and program terminated")

if __name__ == "__main__":
    # Change these as needed
    interface = "can0"
    db_path = "can_messages.db"
    main(interface, db_path)
