import logging
import os
import threading
import time

from garage.cpx import CircuitPlaygroundExpress
from garage.omega import getSideDoorState

logging.basicConfig(format='%(asctime)-15s %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class GarageController(threading.Thread):
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

  def stop(self):
    self._running = True

  def run(self):
    activation_count = 0

    self._running = True

    while self._running:
      try:
        logger.info('Connecting to CPX...')
        cpx = CircuitPlaygroundExpress()

        logger.debug('Entering main CPX interaction loop.')
        while self._running:
          sensor_data = cpx.getSensorData()
          if sensor_data == None:
            continue
          new_state,new_temperature = sensor_data
          logger.debug('CPX State: {}, temperature: {}'.format(new_state, new_temperature))

          if (self._state & 0x01) == 0:  # not activated
            if new_state & 0x01:         # activate
              if new_state > 3 or getSideDoorState() == 'Open'\
                      or self.remotely_activated:
                logger.debug('Turning on relay.')
                os.system('relay-exp 0 1')
              self.remotely_activated = False
              activation_count += 1
            elif self.remotely_activated:
              logger.info('Requesting Activation...')
              cpx.requestActivation()
          elif self._state & 0x01:       # activated
            self.remotely_activated = False
            if (new_state & 0x01) == 0:  # deactivate
              logger.debug('Turning off relay.')
              os.system('relay-exp 0 0')
            else:
              # request deactivation
              logger.info('Requesting Deactivation...')
              cpx.requestDeactivation()

          self._state = new_state

          if new_temperature < 40.0:
            self._temperature = new_temperature
            # logger.debug('Temperature: {}*C'.format(temperature))

          time.sleep(0.1)

      except Exception as e:
        logger.debug(e)
        logger.debug('Sleeping for 10 seconds before attempting to reconnect...')
        time.sleep(10)
        logger.debug('Attempting to reconnect...')

