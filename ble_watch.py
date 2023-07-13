from time import sleep
from bleson import get_provider, Observer

def on_advertisement(advertisement):
   #@@@#print(advertisement)
   if advertisement.mfg_data is not None:
      print(advertisement.address, advertisement.uuid128s, advertisement.rssi, advertisement.mfg_data.hex())
      
adapter = get_provider().get_adapter()

observer = Observer(adapter)
observer.on_advertising_data = on_advertisement

observer.start()
sleep(75)
observer.stop()

