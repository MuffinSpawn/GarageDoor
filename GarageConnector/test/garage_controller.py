#!/usr/bin/env python

import json
import logging
import subprocess
import os
import threading
import time

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
    self._state = 2
    self._temperature = 20.0
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

  def getCircuitPlaygroundData(self):
    return (self._state, self._temperature)

  def stop(self):
    self._running = True

  def run(self):
    activation_count = 0

    self._running = True

    while self._running:
      try:
        logger.debug('Connecting to CPX via I2C...')
        while self._running:
          sensor_data = self.getCircuitPlaygroundData()

          if self.remotely_activated:
            self.remotely_activated = False
            if self._state == 2:
              self._state = 8
            else:
              self._state = 2

          time.sleep(0.1)

      except Exception as e:
        logger.error(e)
        logger.info('Sleeping for 10 seconds before attempting to reconnect...')
        time.sleep(10)
        logger.info('Attempting to reconnect...')

garage_controller = GarageController()
app = flask.Flask(__name__)

@app.route('/', methods=['GET','PUT'])
@app.route('/summary/', methods=['GET','PUT'])
def summary():
  return flask.render_template(
    'summary.html',
    state=garage_controller.state,
    temperature=garage_controller.temperature)

@app.route('/json/', methods=['GET'])
def data():
  return flask.jsonify(state=garage_controller.state, temperature=garage_controller.temperature)

@app.route('/activate/', methods=['PUT'])
def activate():
  garage_controller.remotely_activated = True
  return 'OK'

if __name__ == '__main__':
  garage_controller.setDaemon(True)
  garage_controller.start()
  app.debug = True
  app.run(host = '0.0.0.0', port = 5000)
