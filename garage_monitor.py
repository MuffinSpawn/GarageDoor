#!/usr/bin/env python

import logging
import time

import flask

from garage.monitor import GarageMonitor, GarageState

logging.basicConfig(format='%(asctime)-15s %(message)s')

garage_monitor = GarageMonitor()
app = flask.Flask(__name__)

@app.route('/')
@app.route('/status/')
def displayStatus():
    return flask.render_template('status.html', shadow=garage_monitor.shadow)

def main():
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.DEBUG)
  logger.debug('Before connect')
  garage_monitor.connect()
  logger.debug('After connect')
  while(garage_monitor.state == GarageState.UNKNOWN):
    time.sleep(1)

  #app.secret_key = 'super_secret_key'
  app.debug = True
  app.run(host = '0.0.0.0', port = 5000, use_reloader=False)

if __name__ == '__main__':
  main()
