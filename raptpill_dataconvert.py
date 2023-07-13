## Use this to take a Manufacturer Data string from nRF Connect Scan to parse out RAPT Pill Data
import os
from struct import unpack
from ast import literal_eval

calibration = {
        'Yellow' : literal_eval(os.getenv('RAPT_CAL_YELLOW', "None")),
        'unknown': literal_eval(os.getenv('RAPT_CAL_UNKNOWN', "None")),
}

def parse(mfg_data):
   #@@@#color = "unknown"
   # @@@ Until get ID identifying code working, force to the only color I have
   color = "Yellow"

   payload = mfg_data.hex()
   mfg_id = payload[0:4]
   if mfg_id == "4b45" and payload[4:6] == "47":
       # it is a RAPT Pill, but the firmware version annoucement
       firmware_version =  mfg_data[3:]
       LOG.info("Pill Firmware: {}".format(firmware_version))
   elif mfg_id == "5241":
       # OK, it is a RAPT Pill message with data
       msg_type = payload[4:10]

       if (msg_type == "505401"):
           # V1 Format Data
           print('Unable to decode V1 format data: ', payload)
       elif (msg_type == "505464"):
           # Device Type String
           device_type = mfg_data[5:]
           print('Device Type: ({}) {}'.format(device_type.hex(), device_type.decode("utf-8")))
       elif (msg_type == "505402"):
           try:
               # V2 Format Data - get the uncalibrated values
               data = unpack(">BBfHfhhhH",mfg_data[5:])
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
               if (calibration[color]):
                   suffix = "cali"
                   temperatureF += calibration[color]['temp']
                   specific_gravity += calibration[color]['sg']
               else:
                   suffix = "uncali"

               if (pad != 0):
                   print("INVALID FORMAT for RAPT Pill Data:", mfg_data)
               else:
                   if gravity_velocity_valid == 1:
                       print("Pill: {}  Gravity: {:.4f} (Pts/Day: {:.1f}) Temp: {:.1f}C/{:.1f}F Battery: {:.1f}%".format(color, specific_gravity, gravity_velocity, temperatureC, temperatureF, battery))

                   else:
                       print("Pill: {}  Gravity: {:.4f} Temp: {:.1f}C/{:.1f}F Battery: {:.1f}%".format(color, specific_gravity, temperatureC, temperatureF, battery))
           except KeyError:
               print("Device does not look like a RAPT Pill Hydrometer.")

mfg_datas = [b'\x52\x41\x50\x54\x02\x00\x01\xc0\x1c\xf3\x40\x90\xd6\x44\x78\x1e\xff\x3a\x2c\xfe\x36\x1d\xac\x64\x00',  # 7/2 9pm
             b'\x52\x41\x50\x54\x02\x00\x01\xc1\x26\x05\xab\x91\x06\x44\x83\x68\x8a\x24\xf6\xfe\x7a\x33\xe8\x63\xba',  # 7/3 8:38am
             b'\x52\x41\x50\x54\x02\x00\x01\xc0\xcd\xf8\xc4\x91\x36\x44\x82\xfb\x5e\x27\x3a\xfe\xac\x32\x68\x63\xb5',  # 7/3 10:55am             
             b'\x52\x41\x50\x54\x02\x00\x01\xc0\xef\x30\xed\x90\xce\x44\x82\x05\x57\x2b\xf4\xfd\xe1\x2e\xf0\x63\x9e',  # 7/3 6:46pm             
             ]

for mfg_data in mfg_datas:
    parse(mfg_data)
