from datetime import datetime
import json
import logging
import requests
import os
import time

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from garage.omega import getSideDoorState, getSignalStrengths

logging.basicConfig(format='%(asctime)-15s %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GarageConnector(object):
  def __init__(self):
    self._iot = None
    self._connected = False
    self.running = False
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
    logger.info(topic)
    logger.info(message.payload)
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
    logger.debug('Request Status: {}'.format(self.status))

  def update(self, state, state_changed=False):
    try:
      signal_strengths = getSignalStrengths()
      logger.debug('Signal Strengths:\n{}'.format(signal_strengths))

      if state_changed:
        self._iot.publish("$aws/things/GarageDoor/shadow/delete", "", 1)

      payload = {"state": {"reported": {
        "State": "{}".format(state['main']),
        "StateUpdate": state_changed,
        "Temperature": state['temperature'],
        "SideDoorState": state['side'],
        "NETGEAR63": signal_strengths['NETGEAR63'],
        "Omega-11A3": signal_strengths['Omega-11A3'],
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}}
      logger.debug('Publishing shadow update...')
      self._iot.publish("$aws/things/GarageDoor/shadow/update",
                        json.dumps(payload), 1)
      logger.debug('Published shadow update...')
    except Exception as e:
      logger.debug(e)

  def stop(self):
    self.running = False

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
    last_main_door_state = ''
    last_side_door_state = ''
    data = None
 
    logger.debug('Starting shadow connector main outer loop...')
    self.running = True
    while self.running:
      try:
        logger.info('Connecting to AWS...')
        self._iot.connect()

        logger.info('Subscribing for Shadow Updates...')
        self._iot.subscribe("$aws/things/GarageDoor/shadow/update/accepted", 1,
                            self.updateCallback)
        self._iot.subscribe("$aws/things/GarageDoor/shadow/update/rejected", 1,
                            self.updateCallback)
        self._iot.subscribe("$aws/things/GarageDoor/shadow/update/delta", 1,
                            self.updateCallback)
        logger.info('Subscribed for Shadow Updates.')

        logger.debug('Starting shadow connector main inner loop...')
        while self.running:
          if self.remotely_activated:
            logger.debug('Requesting activation...')
            requests.put('http://localhost:5000/activate/')
            self.remotely_activated = False

          try:
            response = requests.get('http://localhost:5000/json/')
            data = response.json()
            logger.debug('Controller Data: {}'.format(data))
          except Exception as e:
            logger.debug(e)
            time.sleep(5)
            continue

          side_door_state = getSideDoorState()
          logger.debug('Side Door State: {}'.format(side_door_state))

          full_state = {
            "main": data['state'],
            "temperature": data['temperature'],
            "side": side_door_state
          }

          duration = time.time() - start_time

          if last_main_door_state != data['state'] or\
             last_side_door_state != side_door_state:
            logger.debug('State changed. Updating shadow...')
            self.update(full_state, True)
            start_time = time.time()
          elif duration > 600:
            logger.debug('Timer lapsed. Updating shadow...')
            self.update(full_state)
            start_time = time.time()

          last_main_door_state = data['state']
          last_side_door_state = side_door_state
          time.sleep(1)
      except Exception as e:
        logger.debug(e)
        try:
          self._iot.disconnect()
        except:
          pass
        logger.debug('Sleeping for 10 seconds before attempting to reconnect to AWS...')
        time.sleep(10)

if __name__ == '__main__':
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.INFO)
  garage_connector = GarageConnector()
  garage_connector.run()
