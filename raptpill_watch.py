from time import sleep
from struct import unpack
from bleson import get_provider, Observer
from bleson.logger import DEBUG, ERROR, WARNING, INFO, set_level

def on_advertisement(advertisement):
   #@@@#print(advertisement)
   if advertisement.mfg_data is not None:
      rssi = advertisement.rssi
      uuid128 = advertisement.uuid128s
      address = advertisement.address
      payload = advertisement.mfg_data.hex()
      #@@@#print(payload)
      mfg_id = payload[0:4]
      if mfg_id == "5241":
         msg_type = payload[4:10]
         if (msg_type == "505401"):
            # V1 Format Data
            print('V1 format data: ', payload)
         elif (msg_type == "505464"):
            # Device Type String
            device_type = advertisement.mfg_data[5:]
            print('Device Type: ({}) {}'.format(device_type.hex(), device_type.decode("utf-8")))
         elif (msg_type == "505402"):
            # V2 Format Data
            data = unpack(">BBfHfhhhH",advertisement.mfg_data[5:])
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
            #@@@#print(payload,data)
            if (pad != 0):
               print("INVALID FORMAT")
            elif gravity_velocity_valid == 1:
               print("Pill: {}  Gravity: {:.4f} (Pts/Day: {:.1f}) Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {}".format(address.address, specific_gravity, gravity_velocity, temperatureC, temperatureF, battery, rssi))
            else:
               print("Pill: {}  Gravity: {:.4f} Temp: {:.1f}C/{:.1f}F Battery: {:.1f}% RSSI: {}".format(address.address, specific_gravity, temperatureC, temperatureF, battery, rssi)) 


set_level(ERROR)

adapter = get_provider().get_adapter()

observer = Observer(adapter)
observer.on_advertising_data = on_advertisement

observer.start()
sleep(75)
observer.stop()

