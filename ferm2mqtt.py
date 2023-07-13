#!/usr/bin/env python3
"""Wrapper for reading messages from RAPT Pill wireless hydrometer and forwarding them to MQTT topics. 

The device is a Bluetooth Low Energy (BLE) device that sends out a
set of 6 advertisements for every interval as set in the Pill.

The code is roughly based on tilt2mqtt.py

Details of RAPT Pill data format can be found here:
https://gitlab.com/rapt.io/public/-/wikis/Pill-Hydrometer-Bluetooth-Transmissions

The raw values read from the RAPT Pill are (possibly) uncalibrated and should be calibrated before use. The script works a follows,

 1. Listen for local BLE devices
 2. If found the callback is triggered
  * Use Manufacturer ID "5241" (0x4152) to determine that it is from a RAPT Pill (cannot yet distinguish multiple Pills)
  * Extract and convert measurements from the device
  * Construct a JSON payload
  * Send payload to the MQTT server
 3. Stop listening and sleep for X minutes before getting a new measurement

This script has been tested on Linux.

# How to run

First install Python dependencies

 pip install beacontools paho-mqtt requests pybluez

Run the script,

 python raptpill2mqtt.py

Note: A MQTT server is required.

"""

from time import sleep
from bleson import get_provider, Observer
from bleson.logger import DEBUG, ERROR, WARNING, INFO, set_level
from datetime import datetime

import struct
import logging as lg
import os
import json
import paho.mqtt.publish as publish
import requests
from ast import literal_eval

#
# Constants
#
#@@@#sleep_interval = 60.0*10  # How often to listen for new messages in seconds
sleep_interval = 60.0*5  # How often to listen for new messages in seconds

lg.basicConfig(level=lg.INFO)
LOG = lg.getLogger()

# Create handlers
c_handler = lg.StreamHandler()
f_handler = lg.FileHandler('/tmp/ferm2mqtt.log')
#@@@#c_handler.setLevel(lg.INFO)
#@@@#f_handler.setLevel(lg.INFO)
c_handler.setLevel(lg.WARNING)
f_handler.setLevel(lg.WARNING)

# Create formatters and add it to handlers
c_format = lg.Formatter('%(name)s - %(levelname)s - %(message)s')
f_format = lg.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
c_handler.setFormatter(c_format)
f_handler.setFormatter(f_format)

# Add handlers to the logger
LOG.addHandler(c_handler)
LOG.addHandler(f_handler)

# Unique bluetooth UUIDs for Tilt sensors
TILTS = {
        'a495bb10c5b14b44b5121370f02d74de': 'Red',
        'a495bb20c5b14b44b5121370f02d74de': 'Green',
        'a495bb30c5b14b44b5121370f02d74de': 'Black',
        'a495bb40c5b14b44b5121370f02d74de': 'Purple',
        'a495bb50c5b14b44b5121370f02d74de': 'Orange',
        'a495bb60c5b14b44b5121370f02d74de': 'Blue',
        'a495bb70c5b14b44b5121370f02d74de': 'Yellow',
        'a495bb80c5b14b44b5121370f02d74de': 'Pink',
        #@@@#'020001c0-1cf3-4090-d644-781eff3a2cfe': 'RAPT Yellow',
}

tilt_calibration = {
        'Red'    : literal_eval(os.getenv('TILT_CAL_RED', "None")),
        'Green'  : literal_eval(os.getenv('TILT_CAL_GREEN', "None")),
        'Black'  : literal_eval(os.getenv('TILT_CAL_BLACK', "None")),
        'Purple' : literal_eval(os.getenv('TILT_CAL_PURPLE', "None")),
        'Orange' : literal_eval(os.getenv('TILT_CAL_ORANGE', "None")),
        'Blue'   : literal_eval(os.getenv('TILT_CAL_BLUE', "None")),
        'Yellow' : literal_eval(os.getenv('TILT_CAL_YELLOW', "None")),
        'Pink'   : literal_eval(os.getenv('TILT_CAL_PINK', "None")),
        'unknown': literal_eval(os.getenv('TILT_CAL_UNKNOWN', "None")),
}

rapt_calibration = {
        'Yellow' : literal_eval(os.getenv('RAPT_CAL_YELLOW', "None")),
        'unknown': literal_eval(os.getenv('RAPT_CAL_UNKNOWN', "None")),
}
#@@@#LOG.info("TILT Blue Calibration: {}".format(calibration['Blue']))


# MQTT Settings
config = {
        'host': os.getenv('MQTT_IP', '127.0.0.1'),
        'port':int(os.getenv('MQTT_PORT', 1883)),
        'auth': literal_eval(os.getenv('MQTT_AUTH', "None")),
        'debug': os.getenv('MQTT_DEBUG', True),
}
#@@@#LOG.info("MQTT Broker: {}:{}  AUTH:{}".format(config['host'], config['port'], config['auth']))
#@@@#LOG.info("AUTH['username']:{}  AUTH['password']:{}".format(config['auth']['username'],config['auth']['password']))

def process_TILT(address, rssi, color, major, minor, prox):
            
    # Get uncalibrated values
    temperature_fahrenheit = float(major)
    specific_gravity = float(minor)/1000

    try:
        # See if have calibration values. If so, use them.
        if (tilt_calibration[color]):
            suffix = "cali"
            temperature_fahrenheit += tilt_calibration[color]['temp']
            specific_gravity += tilt_calibration[color]['sg']
        else:
            suffix = "uncali"
        
        # convert temperature
        temperature_celsius = (temperature_fahrenheit - 32) * 5/9

        # convert gravity
        degree_plato = 135.997*pow(specific_gravity, 3) - 630.272*pow(specific_gravity, 2) + 1111.14*specific_gravity - 616.868

        now = datetime.now()        
        LOG.info("Tilt: {}  Gravity: {:.4f} Temp: {:.1f}C/{:.1f}F RSSI: {} Now: {}".format(color, specific_gravity, temperature_celsius, temperature_fahrenheit, rssi, now))        
        mqttdata = {
            "specific_gravity_"+suffix: "{:.3f}".format(specific_gravity),
            "plato_"+suffix: "{:.2f}".format(degree_plato),
            "temperature_celsius_"+suffix: "{:.2f}".format(temperature_celsius),
            "temperature_fahrenheit_"+suffix: "{:.1f}".format(temperature_fahrenheit),
            "rssi": "{:d}".format(rssi),
            #@@@#"lastActivityTime": datetime.now().strftime("%b %d %Y %H:%M:%S"),
            "lastActivityTime": "{}".format(now),
        }

        # Send message via MQTT server
        publish.single("tilt/{}".format(color), payload=json.dumps(mqttdata), qos=0, retain=True,
                       hostname=config['host'], port=config['port'], auth=config['auth'])
    except KeyError:
        LOG.error("Unknown Tilt color: {}".format(color))
        

def process_iBeacon(address, rssi, mfg_data):
    """Process the iBeacon Message
    """

    color = "unknown"

    # payload is an ASCII string of hex digits which may be an easier way to handle data in some cases
    payload = mfg_data.hex()

    # Only type of message we know
    try:
        # Check Secondary ID and iBeacon length
        (iBeacon_type, iBeacon_len) = struct.unpack(">BB", mfg_data[2:4])

        if (iBeacon_type == 2 and iBeacon_len == 21):
            ## Still possibly a TILT - must check UUID to know for sure
            
            # Big Endian
            # 128-bit UUID
            # 16-bit MAJOR
            # 16-bit MINOR
            # 8-bit Proximity
            uuid = payload[8:40]

            try:
                color = TILTS[uuid]
            except KeyError:
                LOG.info("Unable to decode Tilt color. Probably some other iBeacon. Message was {}".format(payload))
                return

            # If reach here, then must be a known TILT color - process as if TILT
            (major, minor, prox) = struct.unpack(">HHB", mfg_data[20:])

            process_TILT(address, rssi, color, major, minor, prox)
                        
    except struct.error as e:
        LOG.error("Could not unpack iBeacon message: {}".format(e))
        
            
def process_RAPTPILL(address, rssi, mfg_data):
    """Process the RAPT Pill Message
    """

    #@@@#color = "unknown"
    # @@@ Until get ID identifying code working, force to the only color I have
    color = "Yellow"
    
    payload = mfg_data.hex()
    msg_type = payload[4:10]

    if (msg_type == "505401"):
        # V1 Format Data
        LOG.warning('Unable to decode V1 format data: ', payload)
    elif (msg_type == "505464"):
        # Device Type String
        device_type = mfg_data[5:]
        LOG.info('Device Type: ({}) {}'.format(device_type.hex(), device_type.decode("utf-8")))
    elif (msg_type == "505402"):
        try:
            # V2 Format Data - get the uncalibrated values
            data = struct.unpack(">BBfHfhhhH", mfg_data[5:])
            # Pad (specified to always be 0x00)
            pad = data[0]
            # If 0, gravity velocity is invalid, if 1, it is valid
            gravity_velocity_valid = data[1]
            # floating point, points per day, if gravity_velocity_valid is 1
            gravity_velocity = data[2]
            # temperature in Kelvin, multiplied by 128
            temperatureC = (data[3] / 128) - 273.15
            temperatureF = (temperatureC * 9/5) + 32
            # specific gravity, floating point, apparently in points
            specific_gravity = data[4] / 1000
            # raw accelerometer dta * 16, signed
            accel_x = data[5] / 16
            accel_y = data[6] / 16
            accel_z = data[7] / 16
            # battery percentage * 256, unsigned
            battery = data[8] / 256

            # See if have calibration values. If so, use them.
            if (rapt_calibration[color]):
                suffix = "cali"
                temperatureF += rapt_calibration[color]['temp']
                specific_gravity += rapt_calibration[color]['sg']
            else:
                suffix = "uncali"

            if (pad != 0):
                LOG.error("INVALID FORMAT for RAPT Pill Data:", mfg_data)
            else:
                if gravity_velocity_valid == 1:
                    now = datetime.now()
                    LOG.info("Pill: {}  Gravity: {:.4f} (Pts/Day: {:.1f}) Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {} Now: {}".format(address.address, specific_gravity, gravity_velocity, temperatureC, temperatureF, battery, rssi, now))
                    mqttdata = {
                        "specific_gravity_"+suffix: "{:.4f}".format(specific_gravity),
                        "specific_gravity_pts_per_day_"+suffix: "{:.1f}".format(gravity_velocity),
                        "temperature_celsius_"+suffix: "{:.2f}".format(temperatureC),
                        "temperature_fahrenheit_"+suffix: "{:.1f}".format(temperatureF),
                        "battery": "{:.1f}".format(battery),
                        "rssi": "{:d}".format(rssi),
                        #@@@#"lastActivityTime": datetime.now().strftime("%b %d %Y %H:%M:%S"),
                        "lastActivityTime": "{}".format(now),
                    }

                else:
                    now = datetime.now()
                    LOG.info("Pill: {}  Gravity: {:.4f} Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {} Now: {}".format(address.address, specific_gravity, temperatureC, temperatureF, battery, rssi, now))
                    mqttdata = {
                        "specific_gravity_"+suffix: "{:.4f}".format(specific_gravity),
                        "temperature_celsius_"+suffix: "{:.2f}".format(temperatureC),
                        "temperature_fahrenheit_"+suffix: "{:.1f}".format(temperatureF),
                        "battery": "{:.1f}".format(battery),
                        "rssi": "{:d}".format(rssi),
                        #@@@#"lastActivityTime": datetime.now().strftime("%b %d %Y %H:%M:%S"),
                        "lastActivityTime": "{}".format(now),
                    }

                # Send message via MQTT server
                publish.single("rapt/pill/{}".format(color), payload=json.dumps(mqttdata), qos=0, retain=True,
                               hostname=config['host'], port=config['port'], auth=config['auth'])
        except struct.error as e:
            LOG.error("Could not unpack RAPT Pill Hydrometer message: {}".format(e))
        except KeyError:
            LOG.error("Device does not look like a RAPT Pill Hydrometer.")

    else:
        # Unknown Message Format
        LOG.warning('Unknown RAPT Pill Message Type (', msg_type, ') data: ', payload)
        
            
def on_advertisement(advertisement):
    """Message recieved from BLE Beacon
    """

    if advertisement.mfg_data is not None:
        rssi = advertisement.rssi
        uuid128 = advertisement.uuid128s
        address = advertisement.address
        payload = advertisement.mfg_data.hex()
        mfg_id = payload[0:4]
        if mfg_id == "4b45" and payload[4:6] == "47":
            # it is a RAPT Pill, but the firmware version annoucement
            firmware_version =  advertisement.mfg_data[3:]
            LOG.info("Pill Firmware: {}".format(firmware_version))
        elif mfg_id == "4c00":
            # Apple ID so treat as an iBeacon which may be a Tilt
            LOG.debug(advertisement)
            process_iBeacon(advertisement.address, advertisement.rssi, advertisement.mfg_data)
        elif mfg_id == "5241":
            # OK, it is a RAPT Pill message with data
            LOG.debug(advertisement)
            process_RAPTPILL(advertisement.address, advertisement.rssi, advertisement.mfg_data)
            

def scan(scantime=25.0):        
    LOG.info("Create BLE Scanner")
    adapter = get_provider().get_adapter()

    observer = Observer(adapter)
    observer.on_advertising_data = on_advertisement
 
    LOG.info("Started scanning")
    # Start scanning
    observer.start()
   
    # Time to wait for RAPT Pill to respond
    sleep(scantime)

    # Stop again
    observer.stop()
    LOG.info("Stopped scanning")
   

# Set Log level for bleson scanner to ERROR to prevent the large number of WARNINGs from going into the log
set_level(ERROR)
        
while(1):

    # Scan for iBeacons of RAPT Pill for 75 seconds
    scan(75.0)

    #@@@## Test mqtt publish with sample data
    #@@@#callback("ea:ca:eb:f0:0f:b5", -95, "", {'uuid': 'a495bb60-c5b1-4b44-b512-1370f02d74de', 'major': 73, 'minor': 989})
    #@@@#sleep(2.0)

    # Wait until next scan period
    sleep(sleep_interval)
