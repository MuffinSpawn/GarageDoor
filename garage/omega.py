import json
import logging
import subprocess

logging.basicConfig(format='%(asctime)-15s %(message)s')
logger = logging.getLogger(__name__)

def getSideDoorState():
  status_params = {'command':'status', 'params':{'gpio':'0'}}
  gpio_data_raw = subprocess.check_output(
    ["/bin/ubus", "call", "onion", "gpio", json.dumps(status_params)])
  gpio_data = json.loads(gpio_data_raw)
  if gpio_data['direction'] != 'input':
    set_dir_params = {'command':'set-direction',
                      'params':{'gpio':'0', 'value':'input'}}
    subprocess.call(
      ["/bin/ubus", "call", "onion", "gpio", json.dumps(set_dir_params)])
    get_params = {'command':'get', 'params':{'gpio':'0'}}
    gpio_data_raw = subprocess.check_output(
      ["/bin/ubus", "call", "onion", "gpio", json.dumps(get_params)])
    gpio_data = json.loads(gpio_data_raw)
  logger.debug('GPIO Data: {}'.format(gpio_data))

  state = 'Closed'
  if gpio_data['value'] == '1':
    state = 'Open'
  return state

def getSignalStrengths():
  wifi_data_raw = subprocess.check_output(["/bin/ubus", "call", "onion", "wifi-scan", "{\'device\':\'ra0\'}"])
  wifi_data = json.loads(wifi_data_raw)
  signal_strengths = {}
  for record in wifi_data['results']:
    signal_strengths[record['ssid']] = record['signalStrength']

  if not 'NETGEAR63' in signal_strengths:
    signal_strengths['NETGEAR63'] = 0
  if not 'Omega-11A3' in signal_strengths:
    signal_strengths['Omega-11A3'] = 0
  return signal_strengths

