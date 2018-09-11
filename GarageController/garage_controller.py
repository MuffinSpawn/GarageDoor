#!/usr/bin/env python

import json
import logging
import subprocess
import os
import threading
import time

from OmegaExpansion import onionI2C

import flask

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class GarageController(threading.Thread):
  DATA_SIZE = 7
  STATE_NAMES = ['None', 'Activated',
                'Closed', 'Closed/Activated',
                'Open', 'Open/Activated', '', '',
                'FullyOpen', 'FullyOpen/Activated']

  def __init__(self):
    threading.Thread.__init__(self)
    self._running = False
    self._state = 0
    self._temperature = 0.0
    self.remotely_activated = False

  @property
  def state(self):
    return GarageController.STATE_NAMES[self._state]

  @property
  def temperature(self):
    return self._temperature

  @classmethod
  def fletcher16(cls, data):
    # print(data)
    sum1 = int(0)
    sum2 = int(0)
    for byte in data:
      sum1 = (sum1 + byte) % 255
      sum2 = (sum2 + sum1) % 255
    return (sum2 << 8) | sum1

  @classmethod
  def getCircuitPlaygroundData(cls, i2c):
    sensor_data = i2c.readBytes(0x12, 0x00, GarageController.DATA_SIZE)
    calculated_checksum = GarageController.fletcher16(sensor_data[:-2])

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

  def stop(self):
    self._running = True

  def run(self):
    activation_count = 0

    self._running = True

    while self._running:
      try:
        logger.debug('Connecting to CPX via I2C...')
        i2c = onionI2C.OnionI2C(0)

        while self._running:
          sensor_data = self.getCircuitPlaygroundData(i2c)
          if sensor_data == None:
            continue
          new_state,new_temperature = sensor_data

          if (self._state & 0x01) == 0:  # not activated
            if new_state & 0x01:         # activate
              os.system('relay-exp 0 1')
              activation_count += 1
          elif self._state & 0x01:       # activated
            if (new_state & 0x01) == 0:  # deactivate
              os.system('relay-exp 0 0')
            else:
              # request deactivation
              logger.info('Requesting Deactivation...')
              i2c.writeBytes(0x12, 0x00, [0xBB])

          self._state = new_state

          if new_temperature < 40.0:
            self._temperature = new_temperature
          # logger.debug('Temperature: {}*C'.format(temperature))

          if self.remotely_activated:
            self.remotely_activated = False
            logger.info('Requesting Activation...')
            i2c.writeBytes(0x12, 0x00, [0xAA])

          time.sleep(0.1)

      except Exception as e:
        logger.error(e)
        logger.info('Sleeping for 10 seconds before attempting to reconnect...')
        time.sleep(10)
        logger.info('Attempting to reconnect...')

garage_controller = GarageController()
app = flask.Flask(__name__)

@app.route('/', methods=['GET','PUT'])
@app.route('/summary', methods=['GET','PUT'])
def summary():
  return flask.render_template(
    'summary.html',
    state=garage_controller.state,
    temperature=garage_controller.temperature)

@app.route('/json', methods=['GET'])
def data():
  return flask.jsonify(state=garage_controller.state, temperature=garage_controller.temperature)

'''
payload = {'username': 'bob', 'email': 'bob@bob.com'}
>>> r = requests.put("http://somedomain.org/endpoint", data=payload)
'''
@app.route('/activate', methods=['PUT'])
def activate():
  garage_controller.remotely_activated = True
  return flask.redirect(flask.url_for('/summary'), code=301)

if __name__ == '__main__':
  garage_controller.setDaemon(True)
  garage_controller.start()
  app.debug = True
  app.run(host = '0.0.0.0', port = 5000)
