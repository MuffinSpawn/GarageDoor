#!/usr/bin/env python

import datetime
from enum import Enum
import json
import logging
import os
import re
import subprocess
import threading
import time

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import flask
from http.client import RemoteDisconnected
from python_http_client.exceptions import UnauthorizedError
import requests
import sendgrid
from sendgrid.helpers import mail

logging.basicConfig(format='%(asctime)-15s %(message)s')

state_re = re.compile('<GarageState\.([A-Z][A-Z]*):..*')
type_re = re.compile('<GarageEventType\.([A-Z][A-Z]*_[A-Z][A-Z]*):..*')

class GarageState(Enum):
  UNKNOWN = 0
  CLOSED = 1
  OPEN = 2
  EXTENDED_OPEN = 3

  def __str__(self):
    default_string = super.__str__(self)
    return state_re.match(default_string).group(1)

class GarageEventType(Enum):
  ANY_OPENED = 0
  ALL_CLOSED = 1
  PERIODIC_UPDATE = 2
  INIT_OPEN = 3
  INIT_CLOSED = 4

  def __str__(self):
    default_string = super.__str__(self)
    return type_re.match(default_string).group(1)

class GarageEvent():
  def __init__(self, event_type, shadow):
    self.type = event_type
    self.shadow = shadow

class GarageMonitor(object):
  # Events: any opened, all closed, periodic update, 
  transition_table = [[GarageState.OPEN,          GarageState.CLOSED, GarageState.UNKNOWN, GarageState.OPEN, GarageState.CLOSED],
                      [GarageState.OPEN,          GarageState.CLOSED, GarageState.CLOSED, GarageState.UNKNOWN, GarageState.UNKNOWN],
                      [GarageState.OPEN,          GarageState.CLOSED, GarageState.EXTENDED_OPEN, GarageState.UNKNOWN, GarageState.UNKNOWN],
                      [GarageState.EXTENDED_OPEN, GarageState.CLOSED, GarageState.EXTENDED_OPEN, GarageState.UNKNOWN, GarageState.UNKNOWN]]
  timeout_duration = 600

  def __init__(self):
    self._logger = logging.getLogger(self.__class__.__name__)
    self._logger.setLevel(logging.DEBUG)
    self._config = None
    self._iot = None
    self._opened_time = None
    self.running = False
    self.state = GarageState.UNKNOWN
    self.history = []
    self._message_index = 0

  def handleEvent(self, event, shadow):
    self._message_index = shadow['version']
    self._logger.info('Event: {}'.format(event.type))
    last_state = self.state
    self.state = self.transition_table[self.state.value][event.type.value]
    self._logger.info('Last State: {}\tCurrent State: {}'.format(last_state, self.state))
    self.history.append(shadow)
    if last_state != self.state or self.state == GarageState.EXTENDED_OPEN:
      self.sendEmail(shadow, init=(event.type.value >= GarageEventType.INIT_OPEN.value))
    if self.state == GarageState.CLOSED:
      self.history = []

  def onlineCallback(self, client):
    self._logger.warn('Connected to AWS IoT')
    self._connected = True

  def offlineCallback(self, client):
    self._logger.warn('NOT Connected to AWS IoT')
    self._connected = False

  def getCallback(self, client, userdata, message):
    topic = message.topic
    self._logger.debug(topic)
    self._logger.debug('Message: {}'.format(dir(message)))
    if topic.endswith('accepted'):
      shadow = json.loads(message.payload)
      self._logger.debug('Fetched Shadow:\n{}'.format(shadow))

      mainState = shadow['state']['reported']['State']
      sideState = shadow['state']['reported']['SideDoorState']
      event = None
      if mainState == 'Closed' and sideState == 'Closed':
        event = GarageEvent(GarageEventType.INIT_CLOSED, shadow)
      else:
        event = GarageEvent(GarageEventType.INIT_OPEN, shadow)

      self.handleEvent(event, shadow)

      '''
        shadow['state']['reported']['State'],
        shadow['state']['reported']['SideDoorState'],
        shadow['state']['reported']['Temperature'],
        shadow['state']['reported']['Omega-11A3']))
      '''
    elif topic.endswith('rejected'):
      self._logger.error('The status request was rejected.')
    else:
      self._logger.error('Update callback received an invalid topic: {}'.format(topic))
    self._finished = True

  def updateCallback(self, client, userdata, message):
    topic = message.topic
    self._logger.debug(topic)
    if topic.endswith('accepted'):
      shadow = json.loads(message.payload)
      self._logger.info('A shadow update was accepted:\n{}'.format(shadow))

      if shadow['version'] <= self._message_index:
        self._logger.info('Skipping repeat message with index {}'.format(shadow['version']))
        return

      mainState = shadow['state']['reported']['State']
      sideState = shadow['state']['reported']['SideDoorState']
      stateUpdate = shadow['state']['reported']['StateUpdate']
      event = None
      if stateUpdate:
        if mainState == 'Closed' and sideState == 'Closed':
          event = GarageEvent(GarageEventType.ALL_CLOSED, shadow)
        else:
          event = GarageEvent(GarageEventType.ANY_OPENED, shadow)
      else:
        if mainState == 'Closed' and sideState == 'Closed':
          if self.state != GarageState.CLOSED:
            event = GarageEvent(GarageEventType.ALL_CLOSED, shadow)
          else:
            event = GarageEvent(GarageEventType.PERIODIC_UPDATE, shadow)
        else:
          if self.state != GarageState.OPEN:
            event = GarageEvent(GarageEventType.ANY_OPENED, shadow)
          else:
            event = GarageEvent(GarageEventType.PERIODIC_UPDATE, shadow)

      self.handleEvent(event, shadow)
    elif topic.endswith('rejected'):
      self._logger.debug('A shadow update was rejected.')
    else:
      self._logger.warn('Received an unhandled update for topic {}.'.format(topic))

  def sendEmail(self, shadow, init=False):
    self._logger.info('Sending email update...')
    intro = 'The garage door changed state'
    if init:
      intro = 'The garage door monitor was started'
    published_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = '''
      {} at {}:
      Main Door State: {}
      Side Door State: {}
      Temperature:     {} *C
      Message Index:   {}
      History:'''.format(intro, published_at,
                shadow['state']['reported']['State'],
                shadow['state']['reported']['SideDoorState'],
                shadow['state']['reported']['Temperature'],
                shadow['version'])
    for datum in self.history:
      message += '\n      {} {} {}'.format(
        datum['state']['reported']['State'],
        datum['state']['reported']['SideDoorState'],
        datum['state']['reported']['Timestamp'])
    self._logger.info('Message:{}'.format(message))
    sg = sendgrid.SendGridAPIClient(apikey=self._config['sgkey'])
    data = {
      "personalizations": [
        {
          "to": [
            {
              "email": self._config['email']
            }
          ],
          "subject": "Home Automation Event"
        }
      ],
      "from": {
        "email": self._config['email']
      },
      "content": [
        {
          "type": "text/plain",
          "value": message
        }
      ]
    }
    try:
      sg.client.mail.send.post(request_body=data)
    except Exception as e:
      self._logger.error('Failed to send status email:\n{}'.format(e))


  def connect(self):
    with open('/etc/awsiot/config.json') as config_file:
      self._config = json.load(config_file)
    aws_host = self._config['awshost']
    aws_port = self._config['awsport']

    caPath = self._config['capath']
    keyPath = self._config['keypath']
    certPath = self._config['certpath']

    self._iot = AWSIoTMQTTClient(self._config['clientid'])
    self._iot.configureEndpoint(aws_host, aws_port)
    self._iot.configureCredentials(caPath, keyPath, certPath)

    start_time = time.time()
    state = ''
    last_state = ''
    data = None

    self._logger.debug('Starting shadow monitor main outer loop...')

    self._logger.info('Connecting to AWS...')
    self._iot.connect()

    self._logger.info('Subscribing for Shadow Updates...')
    self._iot.subscribe("$aws/things/GarageDoor/shadow/update/accepted", 1,
                        self.updateCallback)
    self._iot.subscribe("$aws/things/GarageDoor/shadow/update/rejected", 1,
                        self.updateCallback)
    '''
    self._iot.subscribe("$aws/things/GarageDoor/shadow/update/delta", 1,
                        self.updateCallback)
    '''
    self._logger.info('Subscribed for Shadow Updates.')

    self._logger.info('Fetching the shadow status...')
    self._iot.subscribe("$aws/things/GarageDoor/shadow/get/accepted", 1,
                        self.getCallback)
    self._iot.subscribe("$aws/things/GarageDoor/shadow/get/rejected", 1,
                        self.getCallback)
    self._iot.publish("$aws/things/GarageDoor/shadow/get", "", 1)

    self._logger.debug('Garage Monitor Started')
    self.running = True

garage_monitor = GarageMonitor()
app = flask.Flask(__name__)

@app.route('/')
@app.route('/status/')
def displayStatus():
    return flask.render_template('status.html', shadow=garage_monitor.shadow)

def main():
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.DEBUG)
  logger.debug('Before connect ({})'.format(threading.current_thread()))
  garage_monitor.connect()
  logger.debug('After connect')
  while(garage_monitor.state == GarageState.UNKNOWN):
    time.sleep(1)

  #app.secret_key = 'super_secret_key'
  app.debug = True
  app.run(host = '0.0.0.0', port = 5000, use_reloader=False)

if __name__ == '__main__':
  main()
