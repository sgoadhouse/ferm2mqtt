#!/usr/bin/env python3
"""Wrapper for reading messages from [RAPT Pill wireless hydrometer](https://www.kegland.com.au/products/yellow-rapt-pill-hydrometer-thermometer-wifi-bluetooth/) or [Tilt wireless Hydrometer](https://tilthydrometer.com) and forwarding them to MQTT topics. 

The device acts as a simple Bluetooth Low Energy (BLE) beacon sending its data encoded within the Manufacturing Data. Details of RAPT Pill data format can be found here:
https://gitlab.com/rapt.io/public/-/wikis/Pill-Hydrometer-Bluetooth-Transmissions

The raw values read from the RAPT Pill or Tilt are (possibly) uncalibrated and should be calibrated before use. The script works a follows,

 1. Listen for local BLE devices
 2. If found the callback is triggered
  * Use Manufacturer ID "5241" (0x4152) to determine that it is from a RAPT Pill (cannot yet distinguish multiple Pills)
  * Use Manufacturer ID "4c00" (0x004c) to determine that it is from an iBeacon and check UUID for Tilt color
  * Extract and convert measurements from the device
  * Store in a global under the device's color string for processing later
 3. Every minute, process collected data and:
  * Construct a JSON payload
  * Send payload to the MQTT server

This script has been tested on Linux.

# How to run

If you are on Linux first install the bluetooth packages,

sudo apt-get install libbluetooth-dev

Then install Python dependencies

pip install bleson paho-mqtt requests pybluez schedule

Run the script,

python ferm2mqtt.py

Note: A MQTT server is required.

"""

from time import sleep
from bleson import get_provider, Observer, BDAddress
from bleson.logger import DEBUG, ERROR, WARNING, INFO, set_level
from datetime import datetime

import struct
import logging as lg
import os
import json
import paho.mqtt.publish as publish
import requests
from ast import literal_eval

import threading
import schedule


#
# Constants
#
#@@@#scan_interval = 60.0  # How long to scan in seconds
sleep_interval = 60.0*4  # Num. seconds to wait after scanning for new messages before scan again

lg.basicConfig()
LOG = lg.getLogger()
# UNCOMMENT the below to output DEBUG level (not sure why)
#@@@#LOG.setLevel(lg.NOTSET)

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

# Create classes to hold data during scans
class Tilt:
    def __init__(self):
        self.samples = 0
        self.address = BDAddress()
        self.rssi = 0
        self.temperatureF = 0.0
        self.specific_gravity = 0.0
        self.lastActivityTime = None

    def __repr__(self):
        return f'Tilt(Address: {self.address} Samples: {self.samples} Gravity: {self.specific_gravity:.4f} Temp: {self.temperatureF:.1f}F RSSI: {self.rssi} Now: {self.lastActivityTime})'
        
    def __add__(self, x):
        newTilt = self
        # NOTE: address gets copied over undisturbed
        newTilt.address = x.address
        
        newTilt.samples += 1
        newTilt.rssi += x.rssi
        newTilt.temperatureF += x.temperatureF
        newTilt.specific_gravity += x.specific_gravity
        if (x.lastActivityTime is None):
            newTilt.lastActivityTime = datetime.now()
        else:
            newTilt.lastActivityTime = x.lastActivityTime

        return newTilt
            
    def average(self):
        """Average all values and return to self. Reset samples to 1.
           Leave lastActivityTime as the last set value.
           Leave address undisturbed.
        """
        self.temperatureF /= self.samples
        self.specific_gravity /= self.samples
        self.rssi //= self.samples
        self.samples = 1

tiltsLock = threading.Lock()
Tilts = {
    'Red'   : Tilt(),
    'Green' : Tilt(),
    'Black' : Tilt(),
    'Purple': Tilt(),
    'Orange': Tilt(),
    'Blue'  : Tilt(),
    'Yellow': Tilt(),
    'Pink'  : Tilt(),
}
        
# Create classes to hold data during scans
class RaptPill:
    def __init__(self):
        self.samples = 0
        self.address = BDAddress()
        self.rssi = 0
        self.temperatureC = 0.0
        self.specific_gravity = 0.0
        self.gravity_velocity_valid = False
        self.gravity_velocity_samples = 0
        self.gravity_velocity = 0.0
        self.accel_x = 0.0
        self.accel_y = 0.0
        self.accel_z = 0.0
        self.battery = 0.0
        self.lastActivityTime = None

    def __repr__(self):
        return f'RaptPill(Address: {self.address} Samples: {self.samples} Gravity: {self.specific_gravity:.4f} Temp: {self.temperatureC:.1f}C RSSI: {self.rssi} Battery: {self.battery:.1f}% X/Y/Z: {self.accel_x}/{self.accel_y}/{self.accel_z} Now: {self.lastActivityTime})'
        
    def __add__(self, x):
        newRaptPill = self
        # NOTE: address gets copied over undisturbed
        newRaptPill.address = x.address
        
        newRaptPill.samples += 1
        newRaptPill.rssi += x.rssi
        newRaptPill.temperatureC += x.temperatureC
        newRaptPill.specific_gravity += x.specific_gravity
        newRaptPill.accel_x += x.accel_x
        newRaptPill.accel_y += x.accel_y
        newRaptPill.accel_z += x.accel_z
        newRaptPill.battery += x.battery

        if (x.gravity_velocity_valid):
            newRaptPill.gravity_velocity_samples += 1
            newRaptPill.gravity_velocity += x.gravity_velocity
            newRaptPill.gravity_velocity_valid = True

        if (x.lastActivityTime is None):
            newRaptPill.lastActivityTime = datetime.now()
        else:
            newRaptPill.lastActivityTime = x.lastActivityTime

        return newRaptPill
            
    def average(self):
        """Average all values and return to self. Reset samples to 1.
           Leave lastActivityTime as the last set value.
           Leave address undisturbed.
        """
        self.temperatureC /= self.samples
        self.specific_gravity /= self.samples
        self.rssi //= self.samples
        self.accel_x /= self.samples
        self.accel_y /= self.samples
        self.accel_z /= self.samples
        self.battery /= self.samples
        self.samples = 1
        
        if (self.gravity_velocity_valid):
            # If gravity_velocity is valid, average over the number of valid samples we got. 
            self.gravity_velocity /= self.gravity_velocity_samples
            self.gravity_velocity_samples = 1

raptpillsLock = threading.Lock()
RaptPills = {
    'Red'   : RaptPill(),
    'Blue'  : RaptPill(),
    'Green' : RaptPill(),
    'Yellow': RaptPill(),
}
        
# Unique bluetooth UUIDs for Tilt sensors
TILT_UUIDS = {
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
        #@@@#'unknown': literal_eval(os.getenv('TILT_CAL_UNKNOWN', "None")),
}

rapt_calibration = {
        'Red'    : literal_eval(os.getenv('RAPT_CAL_RED',    "None")),
        'Blue'   : literal_eval(os.getenv('RAPT_CAL_BLUE',   "None")),
        'Green'  : literal_eval(os.getenv('RAPT_CAL_GREEN',  "None")),
        'Yellow' : literal_eval(os.getenv('RAPT_CAL_YELLOW', "None")),
        #@@@#'unknown': literal_eval(os.getenv('RAPT_CAL_UNKNOWN', "None")),
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

def sg2plato(sg):
    """ Convert Specific Gravity to Plato
    """
    return 135.997*pow(sg, 3) - 630.272*pow(sg, 2) + 1111.14*sg - 616.868

def degreeF2C(fahrenheit):
    """ Convert Degrees Fahrenheit to Celcius
    """
    return (fahrenheit - 32) * 5/9

def degreeC2F(celcius):
    """ Convert Degrees Celcius to Fahrenheit
    """
    return (celcius * 9/5) + 32

def process_TILT(address, rssi, color, major, minor, prox):

    myTilt = Tilt()
    
    # Get uncalibrated values
    myTilt.temperatureF = float(major)
    myTilt.specific_gravity = float(minor)/1000
    myTilt.rssi = rssi
    myTilt.address = address

    try:
        with tiltsLock:
            Tilts[color] += myTilt
            LOG.info(f'PROCESS: Tilt: {color} {Tilts[color]}')    
        
    except KeyError:
        LOG.error("Unknown Tilt color: {}".format(color))

def publish_TILT(color):
    """Publish averaged data for each Tilt device
    """
    
    try:
        with tiltsLock:
            # Check if have anything to publish
            if (Tilts[color].samples < 1):        
                LOG.info("Nothing to publish for Tilt color: {}".format(color))
                return
        
            # next, average all of the collected values and copy results to myTilt
            Tilts[color].average()
            myTilt = Tilts[color]
        
            # re-init data so the next set can be averaged
            # NOTE: if data is not published, it will be lost
            Tilts[color] = Tilt()
        
        # See if have calibration values. If so, use them.
        if (tilt_calibration[color]):
            suffix = "cali"
            myTilt.temperatureF += tilt_calibration[color]['temp']
            myTilt.specific_gravity += tilt_calibration[color]['sg']
        else:
            suffix = "uncali"
        
        # convert temperature
        temperatureC = degreeF2C(myTilt.temperatureF)

        # convert gravity to Plato
        degree_plato = sg2plato(myTilt.specific_gravity)

        # Check that a lastActivityTime exists - if not set to now()
        if (myTilt.lastActivityTime is None):
            lat = datetime.now()
        else:
            lat = myTilt.lastActivityTime
            
        LOG.info("PUBLISH: Tilt: {}  Gravity: {:.4f} Temp: {:.1f}C/{:.1f}F RSSI: {} Now: {}".format(
            color, myTilt.specific_gravity, temperatureC, myTilt.temperatureF, myTilt.rssi, lat))        
        mqttdata = {
            "specific_gravity_"+suffix: "{:.3f}".format(myTilt.specific_gravity),
            "plato_"+suffix: "{:.2f}".format(degree_plato),
            "temperatureC_"+suffix: "{:.2f}".format(temperatureC),
            "temperatureF_"+suffix: "{:.1f}".format(myTilt.temperatureF),
            "rssi": "{:d}".format(myTilt.rssi),
            #@@@#"lastActivityTime": datetime.now().strftime("%b %d %Y %H:%M:%S"),
            "lastActivityTime": "{}".format(lat),
        }

        # Send message via MQTT server
        publish.single("tilt/{}".format(color), payload=json.dumps(mqttdata), qos=0, retain=True,
                       hostname=config['host'], port=config['port'], auth=config['auth'])
        
    except KeyError:
        LOG.error("Unknown Tilt color: {}".format(color))
        

def process_iBeacon(address, rssi, mfg_data):
    """Process the iBeacon Message
    """

    #@@@#color = "unknown"

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
                color = TILT_UUIDS[uuid]
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

            myRaptPill = RaptPill()
            
            # V2 Format Data - get the uncalibrated values
            data = struct.unpack(">BBfHfhhhH", mfg_data[5:])
            # Pad (specified to always be 0x00)
            pad = data[0]
            
            # If 0, gravity velocity is invalid, if 1, it is valid
            myRaptPill.gravity_velocity_valid = bool(data[1])
            # floating point, points per day, if gravity_velocity_valid is 1
            myRaptPill.gravity_velocity = data[2]
            # temperature in Kelvin, multiplied by 128
            myRaptPill.temperatureC = (data[3] / 128) - 273.15
            # specific gravity, floating point, apparently in points
            myRaptPill.specific_gravity = data[4] / 1000
            # raw accelerometer data * 16, signed
            myRaptPill.accel_x = data[5] / 16
            myRaptPill.accel_y = data[6] / 16
            myRaptPill.accel_z = data[7] / 16
            # battery percentage * 256, unsigned
            myRaptPill.battery = data[8] / 256

            myRaptPill.address = address
            myRaptPill.rssi = rssi
            
            if (pad != 0):
                LOG.error("INVALID FORMAT for RAPT Pill Data:", mfg_data)
            else:
                with raptpillsLock:
                    # With mutex locked, update RaptPills
                    RaptPills[color] += myRaptPill
                    LOG.info(f'PROCESS: RaptPill: {color} {RaptPills[color]}')    

        except struct.error as e:
            LOG.error("Could not unpack RAPT Pill Hydrometer message: {}".format(e))
        except KeyError:
            LOG.error("Device does not look like a RAPT Pill Hydrometer.")

    else:
        # Unknown Message Format
        LOG.warning('Unknown RAPT Pill Message Type (', msg_type, ') data: ', payload)
        
def publish_RAPTPILL(color):
    """Publish averaged data for each Rapt Pill device
    """

    try:
        with raptpillsLock:
            # Check if have anything to publish
            if (RaptPills[color].samples < 1):        
                LOG.info("Nothing to publish for RaptPill color: {}".format(color))
                return
        
            # next, average all of the collected values and copy results to myRaptPill
            RaptPills[color].average()
            myRaptPill = RaptPills[color]
        
            # re-init data so the next set can be averaged
            # NOTE: if data is not published, it will be lost
            RaptPills[color] = RaptPill()
        
        # See if have calibration values. If so, use them.
        if (rapt_calibration[color]):
            suffix = "cali"
            myRaptPill.temperatureC += rapt_calibration[color]['temp']
            myRaptPill.specific_gravity += rapt_calibration[color]['sg']
        else:
            suffix = "uncali"

        # convert temperature
        temperatureF = degreeC2F(myRaptPill.temperatureC)

        # Check that a lastActivityTime exists - if not set to now()
        if (myRaptPill.lastActivityTime is None):
            lat = datetime.now()
        else:
            lat = myRaptPill.lastActivityTime
        
        if (myRaptPill.gravity_velocity_valid):
            LOG.info("PUBLISH: Pill: {}  Gravity: {:.4f} (Pts/Day: {:.1f}) Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {} Now: {}".format(
                color, myRaptPill.specific_gravity, myRaptPill.gravity_velocity, myRaptPill.temperatureC, temperatureF, myRaptPill.battery, myRaptPill.rssi, lat))
            mqttdata = {
                "specific_gravity_"+suffix: "{:.4f}".format(myRaptPill.specific_gravity),
                "specific_gravity_pts_per_day_"+suffix: "{:.1f}".format(myRaptPill.gravity_velocity),
                "temperatureC_"+suffix: "{:.2f}".format(myRaptPill.temperatureC),
                "temperatureF_"+suffix: "{:.1f}".format(temperatureF),
                "battery": "{:.1f}".format(myRaptPill.battery),
                "rssi": "{:d}".format(myRaptPill.rssi),
                #@@@#"lastActivityTime": datetime.now().strftime("%b %d %Y %H:%M:%S"),
                "lastActivityTime": "{}".format(lat),
            }

        else:
            LOG.info("PUBLISH: Pill: {}  Gravity: {:.4f} Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {} Now: {}".format(
                color, myRaptPill.specific_gravity, myRaptPill.temperatureC, temperatureF, myRaptPill.battery, myRaptPill.rssi, lat))
            mqttdata = {
                "specific_gravity_"+suffix: "{:.4f}".format(myRaptPill.specific_gravity),
                "temperatureC_"+suffix: "{:.2f}".format(myRaptPill.temperatureC),
                "temperatureF_"+suffix: "{:.1f}".format(temperatureF),
                "battery": "{:.1f}".format(myRaptPill.battery),
                "rssi": "{:d}".format(myRaptPill.rssi),
                #@@@#"lastActivityTime": datetime.now().strftime("%b %d %Y %H:%M:%S"),
                "lastActivityTime": "{}".format(lat),
            }

        # Send message via MQTT server
        publish.single("rapt/pill/{}".format(color), payload=json.dumps(mqttdata), qos=0, retain=True,
                       hostname=config['host'], port=config['port'], auth=config['auth'])

    except KeyError:
        LOG.error("Unknown RaptPill color: {}".format(color))
        
            
def on_advertisement(advertisement):
    """Message recieved from BLE Beacon
    """

    if advertisement.mfg_data is not None:
        #@@@#uuid128 = advertisement.uuid128s
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
    
    sleep(scantime)

    # Stop again
    #
    # NOTE: not sure if bug or what but this does NOT stop
    # scanning. Once you start, it seems you cannot stop
    observer.stop()
    adapter.stop_scanning()
    LOG.info("Stopped scanning - PSYCHE!")
   

def publishAll():

    # Publish all possible Tilts
    for color in Tilts:
        publish_TILT(color)

    # Publish all possible RaptPills
    for color in RaptPills:
        publish_RAPTPILL(color)


def schedule_run_continuously(interval=1):
    """Continuously run, while executing pending jobs at each
    elapsed time interval.
    @return cease_continuous_run: threading. Event which can
    be set to cease continuous run. Please note that it is
    *intended behavior that schedule_run_continuously() does not run
    missed jobs*. For example, if you've registered a job that
    should run every minute and you set a continuous run
    interval of one hour then your job won't be run 60 times
    at each interval but only once.
    """
    cease_continuous_run = threading.Event()

    class ScheduleThread(threading.Thread):
        @classmethod
        def run(cls):
            while not cease_continuous_run.is_set():
                schedule.run_pending()
                sleep(interval)

    continuous_thread = ScheduleThread()
    continuous_thread.start()
    return cease_continuous_run


if __name__ == '__main__':  
    # Set Log level for bleson scanner to ERROR to prevent the large number of WARNINGs from going into the log
    set_level(ERROR)

    # Publish and reset data once every minute
    schedule.every().minute.do(publishAll)

    # Start the background thread for schedule
    stop_run_continuously = schedule_run_continuously()
    
    # Scan for iBeacons of RAPT Pill and collect data
    scan()

    # Publish any captured data
    #@@@#publishAll()
    
    #@@@## Test mqtt publish with sample data
    #@@@#callback("ea:ca:eb:f0:0f:b5", -95, "", {'uuid': 'a495bb60-c5b1-4b44-b512-1370f02d74de', 'major': 73, 'minor': 989})
    #@@@#sleep(2.0)

    # Since scan() CANNOT actually stop the scan and once it starts,
    # on_advertisement() gets called whenever there is another
    # advertisement, simply loop here forever using sleep() to keep from
    # running a VERY tight while loop that will chew up CPU cycles

    while True:
        try:
            # Wait until next interval period
            sleep(sleep_interval)
        except KeyboardInterrupt:
            break
        
    # Stop the background thread
    stop_run_continuously.set()
    
