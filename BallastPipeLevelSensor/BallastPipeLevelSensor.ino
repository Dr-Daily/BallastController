/*
Ballast pipe sensor

The hardware is a Teensy 3.6 with the following connections:
CAN1 has an MCP2562 TXRX
RED is a red LED
GREEN is a green LED

*/
#include <FlexCAN_T4.h>

FlexCAN_T4<CAN0, RX_SIZE_256, TX_SIZE_16> Can0;
FlexCAN_T4<CAN1, RX_SIZE_256, TX_SIZE_16> Can1;

const int port_pin = 6;
const int starboard_pin = 7;
const int center_pin = 8;

bool port_value = 6;
bool starboard_value = 7;
bool center_value = 8;

//LED_BUILTIN = 13;
const int RED = 21;
const int GREEN = 20;
bool RED_state = HIGH; //RED
bool GREEN_state = HIGH; //Green
bool LED_state = HIGH;

bool sensorValue;

elapsedMillis output_timer;
const int output_period = 100; //milliseconds

const long int priority_part = 0x18000000; //Priority 6
const long int pgn_part = 0x1F21100; //127505 (0x1F211): FLUID Level in NMEA

const long int source_part = 57; //J1939 Source address for 57 is the Water Pump Controller

const long int CAN_ID = priority_part + pgn_part + source_part;
CAN_message_t msg;


void setup() {
  pinMode(6, OUTPUT); digitalWrite(6, LOW); /* optional tranceiver enable pin */

  pinMode(LED_BUILTIN, OUTPUT); digitalWrite(LED_BUILTIN, LED_state); 
  pinMode(RED, OUTPUT); digitalWrite(RED, RED_state); 
  pinMode(GREEN, OUTPUT); digitalWrite(GREEN, GREEN_state); 
  pinMode(port_pin, INPUT_PULLUP);
  pinMode(starboard_pin, INPUT_PULLUP);
  pinMode(center_pin, INPUT_PULLUP);

  Can0.begin();
  Can0.setBaudRate(250000);
  Can0.setMaxMB(16);
  Can0.enableFIFO();
  Can0.enableFIFOInterrupt();
  Can0.onReceive(canSniff);
  Can0.mailboxStatus();
  
  Can1.begin();
  Can1.setBaudRate(250000);
  Can1.setMaxMB(16);
  Can1.enableFIFO();
  Can1.enableFIFOInterrupt();
  Can1.onReceive(canSniff);
  Can1.mailboxStatus();
  
  msg.id = CAN_ID;
  msg.len = 8;
  msg.flags.extended = true;
  delay(1000);
}

void canSniff(const CAN_message_t &msg) {
  GREEN_state = !GREEN_state;
  digitalWrite(GREEN, GREEN_state);
}

void loop() {
  // read the values for the water sensors.
  // The value of zero meand no water is detected.
  // The value of 1 means water is present.
  center_value = !digitalRead(center_pin); //0 = Open, 1 = Closed
  port_value = !digitalRead(port_pin); 
  starboard_value = !digitalRead(starboard_pin);
  
  digitalWrite(RED, port_value); 
  digitalWrite(GREEN, starboard_value); 
  digitalWrite(LED_BUILTIN, center_value);
  
  
  Can1.events();

  if ( output_timer >= output_period  ) {
    output_timer = 0;
    LED_state = !LED_state; //Toggle led each message.
    

    
    msg.buf[0] = center_value;
    msg.buf[1] = port_value;
    msg.buf[2] = starboard_value;
    msg.buf[3] = 0xFF;

    uint32_t count = millis();
    memcpy(&msg.buf[4],&count,4); // little endian, 2's Compliment
    
    Can1.write(msg);
    
    // print the results to the Serial Monitor:
    Serial.printf("Port:  %d, Center: %d, Starboard: %d  - CAN1:  %08X ", port_value, center_value, starboard_value, msg.id);
    for ( uint8_t i = 0; i < msg.len; i++ ) {
      Serial.printf("%02X ",msg.buf[i]);
    } 
    Serial.println();
    
  }
}
