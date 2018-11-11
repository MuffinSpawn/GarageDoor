#!/usr/bin/env python

import datetime
from enum import Enum
import json
import logging
import os
import requests
import subprocess
import threading
import time

import flask
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import sendgrid
from sendgrid.helpers import mail

logging.basicConfig(format='%(asctime)-15s %(message)s')

class GarageState(Enum):
  UNKNOWN = 0
  CLOSED = 1
  OPEN = 2
  EXTENDED_OPEN = 3

class GarageEvent(Enum):
  ANY_OPENED = 0
  ALL_CLOSED = 1
  PERIODIC_UPDATE = 2
  INIT_OPEN = 3
  INIT_CLOSED = 4

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
    self.shadow = None
    self.running = False
    self.state = GarageState.UNKNOWN

  def handleEvent(self, event):
    self._logger.info('Event: {}'.format(event))
    last_state = self.state
    self.state = self.transition_table[self.state.value][event.value]
    self._logger.info('Last State: {}\tCurrent State: {}'.format(last_state, self.state))
    if last_state != self.state:
      self.sendEmail(init=(event.value >= GarageEvent.INIT_OPEN.value))

  def onlineCallback(self, client):
    self._logger.warn('Connected to AWS IoT')
    self._connected = True

  def offlineCallback(self, client):
    self._logger.warn('NOT Connected to AWS IoT')
    self._connected = False

  def getCallback(self, client, userdata, message):
    topic = message.topic
    self._logger.debug(topic)
    if topic.endswith('accepted'):
      self.shadow = json.loads(message.payload)
      self._logger.debug('Fetched Shadow:\n{}'.format(self.shadow))

      mainState = self.shadow['state']['reported']['State']
      sideState = self.shadow['state']['reported']['SideDoorState']
      event = None
      if mainState == 'Closed' and sideState == 'Closed':
        event = GarageEvent.INIT_CLOSED
      else:
        event = GarageEvent.INIT_OPEN

      self.handleEvent(event)

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
      self.shadow = json.loads(message.payload)
      self._logger.info('A shadow update was accepted:\n{}'.format(self.shadow))

      mainState = self.shadow['state']['reported']['State']
      sideState = self.shadow['state']['reported']['SideDoorState']
      stateUpdate = self.shadow['state']['reported']['StateUpdate']
      event = None
      if stateUpdate:
        if mainState == 'Closed' and sideState == 'Closed':
          event = GarageEvent.ALL_CLOSED
        else:
          event = GarageEvent.ANY_OPENED
      else:
        if mainState == 'Closed' and sideState == 'Closed':
          if self.state != GarageState.CLOSED:
            event = GarageEvent.ALL_CLOSED
          else:
            event = GarageEvent.PERIODIC_UPDATE
        else:
          if self.state != GarageState.OPEN:
            event = GarageEvent.ANY_OPENED
          else:
            event = GarageEvent.PERIODIC_UPDATE

      self.handleEvent(event)
    elif topic.endswith('rejected'):
      self._logger.debug('A shadow update was rejected.')
    else:
      self._logger.warn('Received an unhandled update for topic {}.'.format(topic))

  def sendEmail(self, init=False):
    self._logger.info('Sending email update...')
    intro = 'The garage door changed state'
    if init:
      intro = 'The garage door monitor was started'
    published_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
          "value": '''
                   {} at {}:
                   Main Door State: {}
                   Side Door State: {}
                   Temperature:     {} *C
                   '''.format(intro, published_at,
                              self.shadow['state']['reported']['State'],
                              self.shadow['state']['reported']['SideDoorState'],
                              self.shadow['state']['reported']['Temperature'])
        }
      ]
    }
    sg.client.mail.send.post(request_body=data)

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
