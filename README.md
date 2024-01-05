
# Ferm2MQTT - Stream Bluetooth Low Energy (BLE) Hydrometers to MQTT

Based Heavily on: https://github.com/sgoadhouse/tilt2mqtt
Which was originally from: https://github.com/LinuxChristian/tilt2mqtt

##### Table of Contents
1. [Inroduction](#intro)
2. [How to run](#howtorun)
3. [Running as a service](#runasservice)
4. [Integrate with Home Assistant](#intwithhass)
5. [Integrate with Brewers Friend](#brewers)

<a name="intro"/>

# Introduction

**Note:** This package requires a MQTT server. To get one read [here](https://philhawthorne.com/setting-up-a-local-mosquitto-server-using-docker-for-mqtt-communication/).

Wrapper for reading messages from [RAPT Pill wireless hydrometer](https://www.kegland.com.au/products/yellow-rapt-pill-hydrometer-thermometer-wifi-bluetooth/) or [Tilt wireless Hydrometer](https://tilthydrometer.com) and forwarding them to MQTT topics. 

The device acts as a simple Bluetooth Low Energy (BLE) beacon sending its data encoded within the Manufacturing Data. Details of RAPT Pill data format can be found here:
https://gitlab.com/rapt.io/public/-/wikis/Pill-Hydrometer-Bluetooth-Transmissions

The raw values read from the RAPT Pill or Tilt are (possibly) uncalibrated and should be calibrated before use. The script works a follows,

 1. Listen for local BLE devices
 2. If found the callback is triggered
  * Use Manufacturer ID "5241" (0x4152) to determine that it is from a RAPT Pill (cannot yet distinguish multiple Pills)
  * Use Manufacturer ID "4c00" (0x004c) to determine that it is from an iBeacon and check UUID for Tilt color
  * Extract and convert measurements from the device
  * Construct a JSON payload
  * Send payload to the MQTT server
 3. Stop listening and sleep for X minutes before getting a new measurement

This script has been tested on Linux.

<a name="howtorun"/>

# How to run

If you are on Linux first install the bluetooth packages,

```bash
sudo apt-get install libbluetooth-dev
```

Then install Python dependencies

```
pip install bleson paho-mqtt requests pybluez schedule
```

Run the script,

```
python ferm2mqtt.py
```

**Note**: If you get a permission error try running the script as root.

The code should now listen for your device and report values on the MQTT topic that matches your device's color.

You can use the mosquitto commandline tool (on Linux) to listen for colors or the built-in MQTT client in Home Assistant,

```bash
mosquitto_sub -t 'rapt/pill/#' -t 'tilt/#'
```

To listen for measurements only from a RAPT Pill Orange device run,

```bash
mosquitto_sub -t 'rapt/pill/Orange/#'
```

To listen for measurements only from a Tilt Red device run,

```bash
mosquitto_sub -t 'tilt/Red/#'
```

If you have a username and password on your MQTT server (recommended)
then must use the URL form to subscribe to messages. Replace `USER`
with your MQTT username, `PASS` with your MQTT password and `MQTT_IP`
with the IP address of your MQTT broker:
```bash
mosquitto_sub -L 'mqtt://USER:PASS@MQTT_IP/rapt/pill/#' -L 'mqtt://USER:PASS@MQTT_IP/tilt/#'
```



If your MQTT server is not running on the localhost you can set the following environmental variables,

| Varable name | Default value 
|--------------|---------------
| MQTT_IP      |     127.0.0.1
| MQTT_PORT    |          1883
| MQTT_AUTH    |          NONE
| MQTT_DEBUG   |    TRUE      

<a name="runasservice"/>

# Running ferm2MQTT as a service on Linux

If you would like to run ferm2MQTT as a service on Linux using systemd add this file to a systemd path (Normally /lib/systemd/system/ferm2mqtt.service or /etc/systemd/system/ferm2mqtt.service)

```bash
# On debian Linux add this file to /lib/systemd/system/ferm2mqtt.service

[Unit]
Description=BLE Hydrometer Service
After=multi-user.target
Conflicts=getty@tty1.service

[Service]
Type=simple
Environment="MQTT_IP=192.168.1.2"
Environment="MQTT_AUTH={'username':\"my_username\", 'password':\"my_password\"}"
Environment="TILT_CAL_YELLOW={'sg':0.024, 'temp':0.0}"
ExecStart=/usr/bin/python3 <PATH TO YOUR FILE>/ferm2mqtt.py
StandardInput=tty-force
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Remember to update MQTT_IP, my_username, my_password, calibration constants and change the PATH variable in the script above. Then update your service,

```
sudo systemctl reload-daemon
```

OR

```
sudo systemctl --system daemon-reload
```

Will also need to enable and start the service:
```
sudo systemctl enable ferm2mqtt
sudo systemctl start ferm2mqtt
```

<a name="intwithhass"/>

# Using ferm2MQTT with Home assistant

Using the MQTT sensor in home assistant you can now listen for new values and create automations rules based on the values (e.g. start a heater if the temperature is too low).

```yaml
  - platform: mqtt
    name: "RAPT Pill Orange - Temperature"
    state_topic: "rapt/pill/Orange"
    value_template: "{{ value_json.temperature_celsius_uncali | float + 0.5 | float | round(2) }}"
    unit_of_measurement: "\u2103"

  - platform: mqtt
    name: "RAPT Pill Orange - Gravity"
    state_topic: "rapt/pill/Orange"
    value_template: "{{ value_json.specific_gravity_uncali | float + 0.002 | float | round(3) }}"
```

Notice that here the calibration value is added directly to the value template in home assistant. 

![Home Assistant - Brewing](http://fredborg-braedstrup.dk/images/HomeAssistant-brewing.png)

<a name="brewers"/>

# Using with Brewers friend

Using the following [gist](https://gist.github.com/LinuxChristian/c00486eaee5a55daa790122ac4236c11) it is possible to stream the calibrated values from home assistant to the brewers friend API via a simple Python script. After this you can add the ferm2mqtt.service to 

![Brewers Friend fermentation overview](http://fredborg-braedstrup.dk/images/BrewersFriend-fermentation.png)
