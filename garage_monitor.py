#!/usr/bin/env python

import json
import logging
import subprocess
import os
import threading
import time

from OmegaExpansion import onionI2C
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

import flask
app = flask.Flask(__name__)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

DATA_SIZE = 7
STATE_NAMES = ['None', 'Activated',
              'Closed', 'Closed/Activated',
              'Open', 'Open/Activated', '', '',
              'FullyOpen', 'FullyOpen/Activated']

def fletcher16(data):
  # print(data)
  sum1 = int(0)
  sum2 = int(0)
  for byte in data:
    sum1 = (sum1 + byte) % 255
    sum2 = (sum2 + sum1) % 255
  return (sum2 << 8) | sum1

class Shadow(threading.Thread):
  def __init__(self, iot):
    threading.Thread.__init__(self)
    self._logger = logging.getLogger(self.__class__.__name__)
    self._logger.setLevel(logging.DEBUG)
    self._iot = iot
    self._connected = False
    self.finished = False
    self.status = ''
    self.remotely_activated = False
    self._state = 0
    self._temperature = 0.0
    self._state_changed = False
    self._do_update = True

  def onlineCallback(self, client):
    logger.warn('Connected to AWS IoT')
    self._connected = True

  def offlineCallback(self, client):
    logger.warn('NOT Connected to AWS IoT')
    self._connected = False

  def updateCallback(self, client, userdata, message):
    topic = message.topic
    self._logger.info(topic)
    self._logger.info(message.payload)
    if topic.endswith('delta'):
      shadowData = json.loads(message.payload)
      #state = shadowData['state']['delta']['State']
      if 'State' in shadowData['state'].keys():
        state = shadowData['state']['State']
        if state == 'Activated':
          self.remotely_activated = True
    elif topic.endswith('accepted'):
      self.status = 'accepted'
    elif topic.endswith('rejected'):
      self.status = 'rejected'
    else:
      self.status = 'invalid response: {}'.format(topic)
    self._logger.debug('Request Status: {}'.format(self.status))
    self.finished = True

  def update(self, state, temperature, state_changed=False):
    self._state = state
    self._temperature = temperature
    self._state_changed = state_changed
    self._do_update = True

  def update(self, state, temperature, state_changed=False):
    try:
      wifi_data_raw = subprocess.check_output(["/bin/ubus", "call", "onion", "wifi-scan", "{\'device\':\'ra0\'}"])
      wifi_data = json.loads(wifi_data_raw)
      signal_strengths = {}
      for record in wifi_data['results']:
        signal_strengths[record['ssid']] = record['signalStrength']

      if state_changed:
        self._iot.publish("$aws/things/Omega-11A3/shadow/delete", "", 1)
      if not 'NETGEAR63' in signal_strengths:
        signal_strengths['NETGEAR63'] = 0
      if not 'Omega-11A3' in signal_strengths:
        signal_strengths['Omega-11A3'] = 0

      logger.debug('Signal Strengths:\n{}'.format(signal_strengths))

      payload = {"state": {"reported": {
        "State": "{}".format(STATE_NAMES[state]),
        "StateUpdate": state_changed,
        "Temperature": temperature,
        "NETGEAR63": signal_strengths['NETGEAR63'],
        "Omega-11A3": signal_strengths['Omega-11A3']}}}
      logger.debug('Publishing shadow update...')
      self._iot.publish("$aws/things/Omega-11A3/shadow/update",
                        json.dumps(payload), 1)
      logger.debug('Published shadow update...')
      self._do_update = False
    except Exception as e:
      logger.error(e)

  def reset(self):
    self.finished = False
    self.remotely_activated = False

  def stop(self):
    self.finished = True

  def run(self):
    self._logger.debug('Starting shadow connector main outer loop...')
    while not self.finished:
      try:
        self._logger.info('Connecting to AWS...')
        self._iot.connect()

        self._logger.info('Subscribing for Shadow Updates...')
        self._iot.subscribe("$aws/things/Omega-11A3/shadow/update/accepted", 1,
                            self.updateCallback)
        self._iot.subscribe("$aws/things/Omega-11A3/shadow/update/rejected", 1,
                            self.updateCallback)
        self._iot.subscribe("$aws/things/Omega-11A3/shadow/update/delta", 1,
                            self.updateCallback)
        self._logger.info('Subscribed for Shadow Updates.')

        self._logger.debug('Starting shadow connector main inner loop...')
        while not self.finished:
          if self._do_update:
            self._update(self._state, self._temperature, self._state_changed)
          time.sleep(1)
      except Exception as e:
        logger.error(e)
        try:
          self._iot.disconnect()
        except:
          pass
        logger.info('Sleeping for 10 seconds before attempting to reconnect to AWS...')
        time.sleep(10)

def read_data(i2c):
  sensor_data = i2c.readBytes(0x12, 0x00, DATA_SIZE)
  calculated_checksum = fletcher16(sensor_data[:-2])

  checksum = 0
  data_length = len(sensor_data)-2
  for index in range(0, 2):
    checksum += int(sensor_data[index+data_length])*(256**index)
  if not calculated_checksum == checksum:
    return None

  state = int(sensor_data[0])
  if state < 2 or state > 9:
    return None

  temperature = 0.0
  for index in range(0, 4):
    temperature += int(sensor_data[index+1])*(256**index)
  temperature /= 100.0
  # logger.debug('Data: {}, {}*C'.format(state, temperature))

  return (state, temperature)

def main():
  state = 0
  temperature = 20.0
  activation_count = 0
  aws_host = "a1qhgyhvs274m3.iot.us-east-2.amazonaws.com"
  aws_port = 8883

  caPath = "/etc/awsiot/RootCA.pem"
  keyPath = "/etc/awsiot/Omega-11A3-private.pem.key"
  certPath = "/etc/awsiot/Omega-11A3-certificate.pem.crt"

  iot = AWSIoTMQTTClient("GarageMonitor")
  iot.configureEndpoint("a1qhgyhvs274m3.iot.us-east-2.amazonaws.com", 8883)
  iot.configureCredentials(caPath, keyPath, certPath)

  while True:
    # try:
      logger.debug('Connecting to CPX via I2C...')
      i2c = onionI2C.OnionI2C(0)

      logger.debug('Creating shadow connector...')
      shadow = Shadow(iot)
      shadow.setDaemon(True)
      logger.debug('Starting shadow connector...')
      shadow.start()

      start_time = time.time()
      while True:
        duration = time.time() - start_time
        if duration > 600:
          # Report the temperature every so often
          shadow.update(state, temperature)
          start_time = time.time()

        sensor_data = read_data(i2c)
        if sensor_data == None:
          continue
        new_state,new_temperature = sensor_data

        if (state & 0x01) == 0:  # not activated
          if new_state & 0x01:         # activate
            os.system('relay-exp 0 1')
            activation_count += 1
        elif state & 0x01:       # activated
          if (new_state & 0x01) == 0:  # deactivate
            os.system('relay-exp 0 0')
          else:
            # request deactivation
            logger.info('Requesting Deactivation...')
            i2c.writeBytes(0x12, 0x00, [0xBB])

        if new_temperature < 40.0:
          temperature = new_temperature
        # logger.debug('Temperature: {}*C'.format(temperature))

        if state != new_state:
          shadow.update(new_state, new_temperature, True)
        elif shadow.finished == True:
          if shadow.remotely_activated == True:
            logger.info('Requesting Activation...')
            i2c.writeBytes(0x12, 0x00, [0xAA])
          shadow.reset()
        state = new_state
        time.sleep(0.1)

'''
    except Exception as e:
      logger.error(e)
      logger.info('Sleeping for 10 seconds before attempting to reconnect...')
      time.sleep(10)
      logger.info('Attempting to reconnect...')
'''
        

if __name__ == '__main__':
  main()
