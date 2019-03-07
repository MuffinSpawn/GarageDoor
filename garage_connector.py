#!/usr/bin/env python

import logging

from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from garage.connector import GarageConnector

logging.basicConfig(format='%(asctime)-15s %(message)s')

if __name__ == '__main__':
  logger = logging.getLogger(__name__)
  logger.setLevel(logging.INFO)
  garage_connector = GarageConnector()
  garage_connector.run()
