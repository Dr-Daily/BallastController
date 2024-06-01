import asyncio
import websockets
import struct
import time
import json
import socket

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



def get_j1939_from_id(can_id):
    #priority
    priority = (PRIORITY_MASK & can_id) >> 26

    #Extended Data Page
    # edp = (EDP_MASK & can_id) >> 25
    
    # Data Page
    # dp = (DP_MASK & can_id) >> 24
    
    # Protocol Data Unit (PDU) Format
    PF = (can_id & PF_MASK) >> 16
    
    # Protocol Data Unit (PDU) Specific
    #PS = (can_id & PS_MASK) >> 8
    
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

async def stream_data(websocket, path):
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
        
        can_id_key = "{:08X}".format(can_id)
        if can_id_key in data["IDs"]:
            data["IDs"][can_id_key]['count']+=1
            data["IDs"][can_id_key]['time_delta']= "{:d}ms".format(int((can_time - data["IDs"][can_id_key]['time'])*1000))
            data["IDs"][can_id_key]['time']=can_time      
        else:
            data["IDs"][can_id_key]={'count': 1}
            data["IDs"][can_id_key]['time']= can_time
            data["IDs"][can_id_key]['time_delta']= 0
        
        data["IDs"][can_id_key]['data'] = " ".join(["{:02X}".format(b) for b in can_data])
        #Parse the CAN ID into J1939
        priority,pgn,da,sa = get_j1939_from_id(can_id)


        if sa in data["Source"]:
            data["Source"][sa]['count']+=1
        else:
            data["Source"][sa]={'count': 1}
        
        if pgn in data["Source"][sa]:
            data["Source"][sa][pgn]['count']+=1
        else:
            data["Source"][sa][pgn] = {'count': 1}
        
        data["Source"][sa][pgn]['data'] = " ".join(["{:02X}".format(b) for b in can_data])

        if (time.time() - start_time) > 1:
            await websocket.send(json.dumps(data))
            start_time = time.time()
        #await asyncio.sleep(1)  # Adjust the interval as needed

async def main():
    async with websockets.serve(stream_data, "0.0.0.0", 8765):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    # Open a socket and bind to it from SocketCAN
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    interface = "can0"

    # Bind to the interface
    sock.bind((interface,))
    asyncio.run(main())

