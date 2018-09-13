#include <Wire.h>

#include <Adafruit_CircuitPlayground.h>

// #include "Adafruit_Circuit_Playground/utility/IRLibSAMD21.h"

const uint8_t PROXIMITY = A10;
const uint8_t CONTACT_SWITCH_CLOSED = 9;
const uint8_t CONTACT_SWITCH_OPEN   = 10;
const uint16_t PROXIMITY_MINIMUM_THRESHOLD = 676;
const uint16_t PROXIMITY_ACTIVATION_THRESHOLD = 680;
const unsigned int SEND_BUFFER_SIZE = 7;
enum State {NONE, ACTIVATED, CLOSED, CLOSED_AND_ACTIVATED, OPEN, OPEN_AND_ACTIVATED, FULLY_OPEN=8, FULLY_OPEN_AND_ACTIVATED};

int tick_count = 0;
int proximity = 0;
State state = NONE;
float temperature = 0.0;
byte send_buffer[SEND_BUFFER_SIZE];
uint8_t current_pixel = 0;
byte rcv_buffer[10];
uint8_t proximity_intensity = 255;
uint8_t idle_intensity = 0;
uint8_t intensity_increment = 10;

void setup() {
  CircuitPlayground.begin(); 
  Serial.begin(9600);

  // I2C
  Wire.begin(0x12);
  Serial.println("Started I2C slave at address 0x12.");
  Wire.onRequest(requestEvent);
  Wire.onReceive(receiveEvent);

  // Status LED
  pinMode(13, OUTPUT);
  digitalWrite(13, LOW);

  // IR TX
  pinMode(25, OUTPUT);
  digitalWrite(25, LOW);

  // Contact switch indicating the door is closed
  pinMode(CONTACT_SWITCH_CLOSED, INPUT);

  // Contact switch indicating the door is fully open
  pinMode(CONTACT_SWITCH_OPEN, INPUT);

  // Initialize sensor acquisition clock
  setupTC1();

  // Initialize NeoPixel LEDs
  CircuitPlayground.clearPixels();
}

void loop() {
  Serial.println(proximity);
  // proximity_intensity = (uint8_t) ((float) (proximity-PROXIMITY_MINIMUM_THRESHOLD)/(PROXIMITY_ACTIVATION_THRESHOLD-PROXIMITY_MINIMUM_THRESHOLD) * 255);
  idle_intensity += intensity_increment;

  // Any state allows activation
  if (proximity > PROXIMITY_ACTIVATION_THRESHOLD) {
    state = (State) (state | ACTIVATED);
  }

  switch (state) {
    case NONE: {
      // initial boot state check
      if (digitalRead(CONTACT_SWITCH_CLOSED) == LOW) {
        state = CLOSED;
      } else if (digitalRead(CONTACT_SWITCH_OPEN) == LOW) {
        state = FULLY_OPEN;
      } else {
        state = OPEN;
      }
      break;
    }
    case ACTIVATED: {
      // initial boot state check (proximity switch activated)
      if (digitalRead(CONTACT_SWITCH_CLOSED) == LOW) {
        state = CLOSED_AND_ACTIVATED;
      } else if (digitalRead(CONTACT_SWITCH_OPEN) == LOW) {
        state = FULLY_OPEN_AND_ACTIVATED;
      } else {
        state = OPEN_AND_ACTIVATED;
      }
      break;
    }
    case CLOSED:
    case CLOSED_AND_ACTIVATED: {
      if (proximity > PROXIMITY_ACTIVATION_THRESHOLD) {
        setPixelsColor(0, 9, uint8_t(random(256)), uint8_t(random(256)), uint8_t(random(256)));
      } else if (proximity > PROXIMITY_MINIMUM_THRESHOLD) {
        setPixelsColor(0, 9, 0, proximity_intensity, 0);
      } else {
        setPixelsColor(0, 9, 0, idle_intensity, 0);
      }
      if (digitalRead(CONTACT_SWITCH_OPEN) == LOW) {
        state = FULLY_OPEN;
      } else if (digitalRead(CONTACT_SWITCH_CLOSED) == HIGH) {
        state = OPEN;
      }
      break;
    }
    case OPEN:
    case OPEN_AND_ACTIVATED: {
      if (proximity > PROXIMITY_ACTIVATION_THRESHOLD) {
        setPixelsColor(0, 9, uint8_t(random(256)), uint8_t(random(256)), uint8_t(random(256)));
      } else if (proximity > PROXIMITY_MINIMUM_THRESHOLD) {
        setPixelsColor(0, 9, 0, 0, proximity_intensity);
      } else {
        setPixelsColor(0, 9, 0, 0, 0);
        current_pixel += 1;
        if (current_pixel > 9) {
          current_pixel = 0;
        }
        if (state & 0x1) {
          CircuitPlayground.setPixelColor(current_pixel, 244, 238, 66);
        } else {
          CircuitPlayground.setPixelColor(current_pixel, 0, 0, 255);
        }
      }
      if (digitalRead(CONTACT_SWITCH_OPEN) == LOW) {
        state = FULLY_OPEN;
      } else if (digitalRead(CONTACT_SWITCH_CLOSED) == LOW) {
        state = CLOSED;
      }
      break;
    }
    case FULLY_OPEN:
    case FULLY_OPEN_AND_ACTIVATED: {
      if (proximity > PROXIMITY_ACTIVATION_THRESHOLD) {
        setPixelsColor(0, 9, uint8_t(random(256)), uint8_t(random(256)), uint8_t(random(256)));
      } else if (proximity > PROXIMITY_MINIMUM_THRESHOLD) {
        setPixelsColor(0, 9, proximity_intensity, 0, 0);
      } else {
        setPixelsColor(0, 9, idle_intensity, 0, 0);
      }
      if (digitalRead(CONTACT_SWITCH_CLOSED) == LOW) {
        state = CLOSED;
      } else if (digitalRead(CONTACT_SWITCH_OPEN) == HIGH) {
        state = OPEN;
      }
      break;
    }
    default: state = NONE;  // reset if the state is invalid
  }
  if (idle_intensity > 150) {
    intensity_increment = -10;
  } else if (idle_intensity < 20) {
    intensity_increment = 10;
  }


  int temp = (int) round(temperature*100);
  uint16_t index = 0;
  send_buffer[index++] = (byte) state;
  send_buffer[index++] = (byte) temp;
  send_buffer[index++] = (byte) (temp >> 8);
  send_buffer[index++] = (byte) (temp >> 16);
  send_buffer[index++] = (byte) (temp >> 24);
  uint16_t checksum = fletcher16(send_buffer, SEND_BUFFER_SIZE-2);
  // Serial.println(checksum);
  send_buffer[index++] = (byte) checksum;
  send_buffer[index++] = (byte) (checksum >> 8);

  /*
  for (int index=0; index<SEND_BUFFER_SIZE-2; ++index) {
    // send_buffer[5] = send_buffer[5] ^ send_buffer[index] ^ 0xAA;
    Serial.print(send_buffer[index]);
    Serial.print(" ");
  }
  Serial.println();
  */

  Serial.println(state);
  /*
  Serial.println(temperature);
  Serial.println(proximity);
  Serial.println(digitalRead(CONTACT_SWITCH_CLOSED));
  Serial.println(digitalRead(CONTACT_SWITCH_OPEN));
  */
  delay(100);
}

void setPixelsColor(uint8_t startIndex, uint8_t stopIndex, uint8_t r, uint8_t g, uint8_t b) {
  for (uint8_t index = startIndex; index <= stopIndex; ++index) {
    CircuitPlayground.setPixelColor(index, r, g, b);
  }
}

uint16_t fletcher16(uint8_t *data, int count) {
  uint16_t sum1 = 0;
  uint16_t sum2 = 0;
  for (int index=0; index<count; ++index) {
    sum1 = (sum1 + data[index]) % 255;
    sum2 = (sum2 + sum1) % 255;
  }
  return (sum2 << 8) | sum1;
}

void requestEvent() {
  /*
  for (int byteIndex=0; byteIndex<4; ++byteIndex) {
    Wire.write((state >> 8*byteIndex) & 0xff);
  }
  */
  Wire.write(send_buffer, SEND_BUFFER_SIZE);
  // Serial.print("Sent 4-byte integer: "); Serial.println(state);
}

void receiveEvent(int count) {
  int index = 0;
  while (Wire.available()) {
    rcv_buffer[index] = Wire.read();
    ++index;
  }
  // Serial.print("REMOTE COUNT: ");
  // Serial.println(count);
  if (count > 1) {
    /*
    for (index = 0; index < count; ++index) {
      Serial.print(rcv_buffer[index]);
      Serial.print(" ");
    }
    Serial.println();
    */
    if (rcv_buffer[1] == 0xAA) {
      state = (State) (state | ACTIVATED);
    } else if (rcv_buffer[1] == 0xBB) {
      state = (State) (state & 0xFE);
    }
  }
}

void TCC1_Handler() {
  Tcc* TC = (Tcc*) TCC1;
  if (TC->INTFLAG.bit.OVF == 1) {
    digitalWrite(25, tick_count % 32 == 0);
    if (tick_count > 32) {
      proximity = analogRead(PROXIMITY);
      temperature = CircuitPlayground.temperature();
      tick_count = 0;
    }
    TC->INTFLAG.bit.OVF = 1;
    ++tick_count;
  }

  if (TC->INTFLAG.bit.MC0 == 1) {
    TC->INTFLAG.bit.MC0 = 1;
  }
}

void setupTC1() {
  // Enable clock for TC
  REG_GCLK_CLKCTRL = (uint16_t) (GCLK_CLKCTRL_CLKEN | GCLK_CLKCTRL_GEN_GCLK0 | GCLK_CLKCTRL_ID_TCC0_TCC1) ;
  while (GCLK->STATUS.bit.SYNCBUSY == 1); // wait for sync

  // The type cast must fit with the selected timer mode
  Tcc* TC = (Tcc*) TCC1;

  TC->CTRLA.reg &= ~TC_CTRLA_ENABLE;   // Disable TC
  while (TC->SYNCBUSY.bit.ENABLE == 1); // wait for sync

  TC->CTRLA.reg |= TC_CTRLA_WAVEGEN_NFRQ; // Set TC as normal Normal Frq
  while (TC->SYNCBUSY.bit.ENABLE == 1); // wait for sync

  TC->CTRLA.reg |= TC_CTRLA_PRESCALER_DIV256;   // Set perscaler

  TC->PER.reg = 0xFF;   // Set counter Top using the PER register but the 16/32 bit timer counts allway to max 
  while (TC->SYNCBUSY.bit.WAVE == 1); // wait for sync

  TC->CC[0].reg = 0xFFF;
  while (TC->SYNCBUSY.bit.CC0 == 1); // wait for sync
 
  // Interrupts
  TC->INTENSET.reg = 0;              // disable all interrupts
  TC->INTENSET.bit.OVF = 1;          // enable overfollow
  TC->INTENSET.bit.MC0 = 1;          // enable compare match to CC0

  // Enable InterruptVector
  NVIC_EnableIRQ(TCC1_IRQn);

  // Enable TC
  TC->CTRLA.reg |= TCC_CTRLA_ENABLE;
  while (TC->SYNCBUSY.bit.ENABLE == 1); // wait for sync
}
