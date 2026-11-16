// ReSpeaker Lite + XIAO ESP32-S3 hardware test.
// Loop: beep -> record 4 s (talk!) -> print mic levels -> play the recording back.
//
// The XMOS chip is the I2S clock MASTER on this board, so the ESP32 runs as
// SLAVE (it follows XMOS's BCLK/WS instead of driving them).
#include <Arduino.h>
#include <driver/i2s_std.h>

// ReSpeaker Lite I2S wiring (XIAO side)
constexpr gpio_num_t PIN_BCLK = GPIO_NUM_8;
constexpr gpio_num_t PIN_WS   = GPIO_NUM_7;
constexpr gpio_num_t PIN_DOUT = GPIO_NUM_43;  // to speaker / codec
constexpr gpio_num_t PIN_DIN  = GPIO_NUM_44;  // from XMOS (processed mics)

constexpr int RATE = 16000;
constexpr int REC_SECONDS = 4;
constexpr size_t REC_SAMPLES = RATE * REC_SECONDS;
constexpr int BLOCK = 256;  // stereo frames per transfer

i2s_chan_handle_t tx = nullptr, rx = nullptr;
int16_t *rec = nullptr;
int32_t buf[2 * BLOCK];     // interleaved L/R, 32-bit slots
int32_t silence[2 * BLOCK] = {0};

bool i2sWrite(const void *data, size_t bytes) {
  size_t written = 0;
  return i2s_channel_write(tx, data, bytes, &written, 1000) == ESP_OK;
}

// Returns stereo frames read (0 on timeout = no clock from XMOS).
size_t i2sRead(void *data, size_t bytes) {
  size_t got = 0;
  if (i2s_channel_read(rx, data, bytes, &got, 1000) != ESP_OK) return 0;
  return got / 8;
}

void writeSilence(size_t frames) {
  while (frames > 0) {
    size_t n = min(frames, (size_t)BLOCK);
    i2sWrite(silence, n * 8);
    frames -= n;
  }
}

void playTone(float hz, float seconds) {
  float phase = 0, inc = 2 * PI * hz / RATE;
  size_t total = RATE * seconds;
  for (size_t n = 0; n < total; n += BLOCK) {
    for (int i = 0; i < BLOCK; i++) {
      int32_t s = (int32_t)(sinf(phase) * 0.3f * 32767) << 16;  // 16-bit audio in the top half
      buf[2 * i] = s;
      buf[2 * i + 1] = s;
      phase += inc;
      if (phase > 2 * PI) phase -= 2 * PI;
    }
    i2sWrite(buf, sizeof(buf));
  }
}

bool record() {
  for (int i = 0; i < 10; i++) {  // discard stale mic data
    writeSilence(i2sRead(buf, sizeof(buf)));
  }
  size_t got = 0;
  int32_t peakL = 0, peakR = 0;
  double sumL = 0;
  while (got < REC_SAMPLES) {
    size_t frames = i2sRead(buf, sizeof(buf));
    if (frames == 0) {
      Serial.println("  -> I2S read timed out: no clock from the XMOS chip (firmware?)");
      return false;
    }
    writeSilence(frames);  // keep the output fed while recording
    for (size_t i = 0; i < frames && got < REC_SAMPLES; i++) {
      int16_t l = buf[2 * i] >> 16, r = buf[2 * i + 1] >> 16;
      peakL = max(peakL, (int32_t)abs(l));
      peakR = max(peakR, (int32_t)abs(r));
      sumL += (double)l * l;
      rec[got++] = l;
    }
  }
  Serial.printf("  mic peak: left=%d right=%d  left rms=%.0f (of 32767)\n",
                peakL, peakR, sqrt(sumL / REC_SAMPLES));
  return true;
}

void playback() {
  for (size_t i = 0; i < REC_SAMPLES; i += BLOCK) {
    size_t n = min((size_t)BLOCK, REC_SAMPLES - i);
    for (size_t k = 0; k < n; k++) {
      int32_t s = ((int32_t)rec[i + k]) << 16;
      buf[2 * k] = s;
      buf[2 * k + 1] = s;
    }
    i2sWrite(buf, n * 8);
  }
}

void setup() {
  Serial.begin(115200);
  delay(2000);  // give the USB serial monitor time to attach
  Serial.println("ReSpeaker Lite test (ESP32 = I2S slave)");

  i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_SLAVE);
  chan_cfg.auto_clear = true;  // send zeros (silence) when we have nothing queued
  ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &tx, &rx));

  i2s_std_config_t std_cfg = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(RATE),
      .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
      .gpio_cfg = {
          .mclk = I2S_GPIO_UNUSED,
          .bclk = PIN_BCLK,
          .ws = PIN_WS,
          .dout = PIN_DOUT,
          .din = PIN_DIN,
          .invert_flags = {.mclk_inv = false, .bclk_inv = false, .ws_inv = false},
      },
  };
  ESP_ERROR_CHECK(i2s_channel_init_std_mode(tx, &std_cfg));
  ESP_ERROR_CHECK(i2s_channel_init_std_mode(rx, &std_cfg));
  ESP_ERROR_CHECK(i2s_channel_enable(tx));
  ESP_ERROR_CHECK(i2s_channel_enable(rx));

  rec = (int16_t *)(psramFound() ? ps_malloc(REC_SAMPLES * 2) : malloc(REC_SAMPLES * 2));
  if (!rec) {
    Serial.println("buffer alloc FAILED");
    while (true) delay(1000);
  }
  Serial.printf("I2S ok, PSRAM %s\n", psramFound() ? "found" : "not found");
}

void loop() {
  Serial.println("beep");
  playTone(440, 0.8);
  Serial.println("recording 4 s... talk now!");
  if (record()) {
    Serial.println("playing back");
    playback();
  }
  writeSilence(RATE * 2);  // 2 s pause
}
