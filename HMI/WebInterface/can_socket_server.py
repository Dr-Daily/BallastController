# sudo systemctl restart can-websocket-server.service
import time
import paho.mqtt.client as mqtt
import json
import socket
import struct

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "j1939/stats"

UPDATE_PERIOD = .75 #second

# To match this data structure, the following struct format can be used:
can_frame_format = "<lB3x8s"

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

    # Protocol Data Unit (PDU) Format
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

j1939_SA={0:{'name':"Engine #1"},
          3:{'name':"Transmission"},
          15:{'name':"Retarder"}
          }

#Make a CAN reading function
def unpack_CAN(can_packet,display=False):
    can_id, can_dlc, can_data = struct.unpack(can_frame_format, can_packet)
    extended_frame = bool(can_id & socket.CAN_EFF_FLAG)
    if extended_frame:
        can_id &= socket.CAN_EFF_MASK
        can_id_string = "{:08X}".format(can_id)
    else: #Standard Frame
        can_id &= socket.CAN_SFF_MASK
        can_id_string = "{:03X}".format(can_id)
    if display:
        hex_data_string = ' '.join(["{:02X}".format(b) for b in can_data[:can_dlc]])
        print("{} {} [{}] {}".format(interface, can_id_string, can_dlc, hex_data_string))
    return can_id, can_dlc, can_data

def publish_stats(client):
    #Setup some defaults
    volts = "N/A"
    rpm = "N/A"
    port_water_sensor = "N/A"
    center_water_sensor = "N/A"
    starboard_water_sensor = "N/A"
    port_fill_level = "N/A"
    center_fill_level = "N/A"
    starboard_fill_level = "N/A"
    port_fill_state = "N/A"
    center_fill_state = "N/A"
    starboard_fill_state = "N/A"
    port_fill_timer = "N/A"
    center_fill_timer = "N/A"
    starboard_fill_timer = "N/A"
    port_switch_state = "N/A"
    center_switch_state = "N/A"
    starboard_switch_state = "N/A"
    center_trim_tab_position = "N/A"
    center_trim_tab_switch_state = "N/A"
    
    data = {"IDs":{},"Source":{}}
    start_time = time.time()
  
    while True:
        # Read the message from the newtork
        can_packet = sock.recv(16)
        can_time = time.time() #This is jittery.
    
        #Parse the bytes into a CAN message
        can_id, can_dlc, can_data = unpack_CAN(can_packet)
        
        #Parse the CAN ID into J1939
        priority,pgn,da,sa = get_j1939_from_id(can_id)


        if sa in data["Source"]:
            data["Source"][sa]['count']+=1
        else:
            data["Source"][sa]={'count': 1}
            data["Source"][sa]['address'] = sa
            data["Source"][sa]['pgns']={}
            try:
                data["Source"][sa]['name'] = j1939_SA[sa]['name']
            except KeyError:
                data["Source"][sa]['name'] = "Unknown"
        
        can_id_key = "{:08X}".format(can_id)
        if pgn in data["Source"][sa]['pgns']:
            data["Source"][sa]['pgns'][pgn]['count']+=1
            data["Source"][sa]['pgns'][pgn]['time_delta']= "{:d}ms".format(
                int((can_time - data["Source"][sa]['pgns'][pgn]['time'])*1000))
        else:
            data["Source"][sa]['pgns'][pgn] = {'count': 1}
            data["Source"][sa]['pgns'][pgn]['id']=can_id_key
            data["Source"][sa]['pgns'][pgn]['time_delta']= 0
            data["Source"][sa]['pgns'][pgn]['da']=da
        
        data["Source"][sa]['pgns'][pgn]['data'] = " ".join(["{:02X}".format(b) for b in can_data])
        data["Source"][sa]['pgns'][pgn]['time']= can_time
            

        if (time.time() - start_time) > UPDATE_PERIOD:
            start_time = time.time()
            client.publish(MQTT_TOPIC, json.dumps(data))


if __name__ == "__main__":

    # Connect to the broker.
    # mosquitto should be running
    client = mqtt.Client()
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    
    # Setup a perpetual loop to catch issues with socketCAN.
    # Other users can take down and bring up CAN, so the socket will fail and 
    # we need to restart again.
    while True:
        try:
            # Open a socket and bind to it from SocketCAN
            sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            interface = "can0"
            # Bind to the interface
            sock.bind((interface,))
            publish_stats(client)
        except Exception as e:
            print(repr(e))
            #Wait for the network to come back up.
            time.sleep(.1)

