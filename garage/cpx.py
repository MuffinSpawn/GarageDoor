import logging

from OmegaExpansion import onionI2C

logging.basicConfig(format='%(asctime)-15s %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class CircuitPlaygroundExpress():
  def __init__(self):
    self.i2c = onionI2C.OnionI2C(0)

  def requestActivation(self):
    self.i2c.writeBytes(0x12, 0x00, [0xAA])

  def requestDeactivation(self):
    self.i2c.writeBytes(0x12, 0x00, [0xBB])

  @classmethod
  def fletcher16(data):
    # print(data)
    sum1 = int(0)
    sum2 = int(0)
    for byte in data:
      sum1 = (sum1 + byte) % 255
      sum2 = (sum2 + sum1) % 255
    return (sum2 << 8) | sum1

  def getSensorData(self):
    sensor_data = self.i2c.readBytes(0x12, 0x00, GarageController.DATA_SIZE)
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
