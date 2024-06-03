import time
import paho.mqtt.client as mqtt
import json

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "sensor/data"

client = mqtt.Client()
client.connect(MQTT_BROKER, MQTT_PORT, 60)

while True:
    sensor_data = {"temperature": 22.5, "humidity": 60}  # Simulate sensor data
    client.publish(MQTT_TOPIC, json.dumps(sensor_data))
    print(f"Published: {sensor_data}")
    time.sleep(2)
