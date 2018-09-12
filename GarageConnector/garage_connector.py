#!/usr/bin/env python

import json
import logging
import requests
import subprocess
import os
import time
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class GarageConnector(object):
  def __init__(self):
    self._logger = logging.getLogger(self.__class__.__name__)
    self._logger.setLevel(logging.DEBUG)
    self._iot = None
    self._connected = False
    self.finished = False
    self.status = ''
    self.remotely_activated = False

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
    #if topic.endswith('delta'):
    if topic.endswith('desired'):
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

  @classmethod
  def getSignalStrengths(cls):
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

  def update(self, state, temperature, state_changed=False):
    try:
      signal_strengths = GarageConnector.getSignalStrengths()
      logger.debug('Signal Strengths:\n{}'.format(signal_strengths))

      if state_changed:
        self._iot.publish("$aws/things/GarageDoor/shadow/delete", "", 1)

      payload = {"state": {"reported": {
        "State": "{}".format(state),
        "StateUpdate": state_changed,
        "Temperature": temperature,
        "NETGEAR63": signal_strengths['NETGEAR63'],
        "Omega-11A3": signal_strengths['Omega-11A3']}}}
      logger.debug('Publishing shadow update...')
      self._iot.publish("$aws/things/GarageDoor/shadow/update",
                        json.dumps(payload), 1)
      logger.debug('Published shadow update...')
    except Exception as e:
      logger.error(e)

  def reset(self):
    self.finished = False
    self.remotely_activated = False

  def stop(self):
    self.finished = True

  def run(self):
    aws_host = "a1qhgyhvs274m3.iot.us-east-2.amazonaws.com"
    aws_port = 8883

    caPath = "/etc/awsiot/RootCA.pem"
    keyPath = "/etc/awsiot/911203a581-private.pem.key"
    certPath = "/etc/awsiot/911203a581-certificate.pem.crt"

    self._iot = AWSIoTMQTTClient("GarageConnector")
    self._iot.configureEndpoint("a1qhgyhvs274m3.iot.us-east-2.amazonaws.com", 8883)
    self._iot.configureCredentials(caPath, keyPath, certPath)
 
    start_time = time.time()
    state = ''
    last_state = ''
    data = None
 
    self._logger.debug('Starting shadow connector main outer loop...')
    while not self.finished:
      try:
        self._logger.info('Connecting to AWS...')
        self._iot.connect()

        self._logger.info('Subscribing for Shadow Updates...')
        self._iot.subscribe("$aws/things/GarageDoor/shadow/update/accepted", 1,
                            self.updateCallback)
        self._iot.subscribe("$aws/things/GarageDoor/shadow/update/rejected", 1,
                            self.updateCallback)
        self._iot.subscribe("$aws/things/GarageDoor/shadow/update/delta", 1,
                            self.updateCallback)
        self._logger.info('Subscribed for Shadow Updates.')

        self._logger.debug('Starting shadow connector main inner loop...')
        while not self.finished:
          if self.remotely_activated:
            logger.debug('Requesting activation...')
            requests.put('http://localhost:5000/activate/')

          try:
            response = requests.get('http://localhost:5000/json/')
            data = response.json()
          except Exception as e:
            logger.error(e)
            time.sleep(5)
            continue

          duration = time.time() - start_time

          if last_state != data['state']:
            logger.debug('State changed. Updating shadow...')
            self.update(data['state'], data['temperature'], True)
            start_time = time.time()
          elif duration > 600:
            logger.debug('Timer lapsed. Updating shadow...')
            self.update(data['state'], data['temperature'])
            start_time = time.time()

          last_state = data['state']
          time.sleep(1)
      except Exception as e:
        logger.error(e)
        try:
          self._iot.disconnect()
        except:
          pass
        logger.info('Sleeping for 10 seconds before attempting to reconnect to AWS...')
        time.sleep(10)

if __name__ == '__main__':
  garage_connector = GarageConnector()
  garage_connector.run()
