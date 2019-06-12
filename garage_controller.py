#!/usr/bin/env python

import logging

import flask

from garage.controller import GarageController

logging.basicConfig(format='%(asctime)-15s %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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
  app.run(host = '0.0.0.0', port = 5000, use_reloader=False)
