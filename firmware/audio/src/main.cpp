// Talking Skeleton: AUDIO device firmware for the ReSpeaker Lite (XIAO ESP32-S3).
//
// Implements the "audio" role of PROTOCOL.md:
//   mic   : XMOS processed voice (left channel) -> 16 kHz s16 mono, 20 ms binary frames -> server
//   play  : server [0x01][env][pcm] frames -> jitter buffer (PSRAM) -> I2S -> codec -> speaker
//   events: play_end{id} -> playback_done{id} once the speaker has actually played it
//
// I2S: the XMOS chip is the clock MASTER; the ESP32 is SLAVE (proven by the test sketch).

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <driver/i2s_std.h>

#include <atomic>

#include "config.h"
#include "skeleton_net.h"  // Wi-Fi list + wss/token setup

// ---------------------------------------------------------------- constants
constexpr gpio_num_t PIN_BCLK = GPIO_NUM_8;
constexpr gpio_num_t PIN_WS = GPIO_NUM_7;
constexpr gpio_num_t PIN_DOUT = GPIO_NUM_43;
constexpr gpio_num_t PIN_DIN = GPIO_NUM_44;

constexpr int RATE = 16000;
constexpr int FRAME = 320;                // 20 ms
constexpr size_t PREBUFFER = RATE / 10;   // wait for 100 ms before starting playback
constexpr uint32_t DONE_DELAY_MS = 60;    // I2S DMA still holds ~40 ms after we hand it data
constexpr uint8_t MSG_AUDIO = 0x01;

// ---------------------------------------------------------------- state
i2s_chan_handle_t tx = nullptr, rx = nullptr;
WebSocketsClient ws;
std::atomic<bool> connected{false};
std::atomic<float> gain{DEFAULT_GAIN};

// Playback ring buffer: single producer (WebSocket callback in loop()),
// single consumer (playbackTask). wpos/rpos count samples forever (never wrap).
int16_t *ring = nullptr;
size_t ringSize = 0;
std::atomic<size_t> wpos{0}, rpos{0};
std::atomic<bool> flushReq{false};

struct PlayEnd {
  uint32_t id;
  size_t endPos;
};
struct PlayDone {
  uint32_t id;
  uint32_t dueMs;
};
struct MicFrame {
  int16_t s[FRAME];
};
QueueHandle_t endQ, doneQ, micQ;

// stats
std::atomic<uint32_t> statUnderruns{0}, statMicDrops{0}, statRingDrops{0}, statMicSent{0};

// ---------------------------------------------------------------- I2S
void i2sInit() {
  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_SLAVE);
  chan.auto_clear = true;   // output silence when we have nothing queued
  chan.dma_desc_num = 4;    // 4 x 10 ms of DMA = low output latency
  chan.dma_frame_num = 160;
  ESP_ERROR_CHECK(i2s_new_channel(&chan, &tx, &rx));

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
}

// ---------------------------------------------------------------- ring buffer
// Push little-endian s16 PCM bytes (may be unaligned) into the ring.
void ringPushBytes(const uint8_t *pcm, size_t bytes) {
  size_t n = bytes / 2;
  size_t w = wpos.load(std::memory_order_relaxed);
  size_t free = ringSize - (w - rpos.load(std::memory_order_acquire));
  if (n > free) {
    statRingDrops += n - free;
    n = free;
  }
  for (size_t i = 0; i < n; i++) {
    int16_t s;
    memcpy(&s, pcm + 2 * i, 2);
    ring[(w + i) % ringSize] = s;
  }
  wpos.store(w + n, std::memory_order_release);
}

// ---------------------------------------------------------------- tasks
void playbackTask(void *) {
  static int32_t out[2 * FRAME];
  bool playing = false;
  for (;;) {
    if (flushReq.exchange(false)) {
      rpos.store(wpos.load());
      playing = false;
    }
    size_t r = rpos.load(std::memory_order_relaxed);
    size_t avail = wpos.load(std::memory_order_acquire) - r;

    PlayEnd pe;
    bool endPending = xQueuePeek(endQ, &pe, 0) == pdTRUE;
    if (!playing && avail > 0 && (avail >= PREBUFFER || endPending)) playing = true;

    size_t n = 0;
    if (playing) {
      n = min(avail, (size_t)FRAME);
      if (n < FRAME && !endPending) statUnderruns++;  // network didn't keep up
      float g = gain.load();
      for (size_t i = 0; i < n; i++) {
        float v = ring[(r + i) % ringSize] * g;
        v = v > 32767.f ? 32767.f : (v < -32768.f ? -32768.f : v);
        int32_t s = ((int32_t)v) << 16;
        out[2 * i] = s;
        out[2 * i + 1] = s;
      }
      rpos.store(r + n, std::memory_order_release);
      if (n == avail) playing = false;  // drained; re-prebuffer next time
    }
    for (size_t i = n; i < FRAME; i++) out[2 * i] = out[2 * i + 1] = 0;

    size_t written;
    i2s_channel_write(tx, out, sizeof(out), &written, portMAX_DELAY);  // paces us at real time

    // Any utterance whose last sample has now gone to the DMA is (almost) done.
    while (xQueuePeek(endQ, &pe, 0) == pdTRUE && rpos.load() >= pe.endPos) {
      xQueueReceive(endQ, &pe, 0);
      PlayDone d{pe.id, (uint32_t)millis() + DONE_DELAY_MS};
      xQueueSend(doneQ, &d, 0);
    }
  }
}

void micTask(void *) {
  static int32_t in[2 * FRAME];
  MicFrame f;
  for (;;) {
    size_t got = 0;
    if (i2s_channel_read(rx, in, sizeof(in), &got, 1000) != ESP_OK || got == 0) {
      Serial.println("[mic] I2S read timeout: no clock from XMOS?");
      continue;
    }
    size_t frames = got / 8;
    for (size_t i = 0; i < frames && i < FRAME; i++) f.s[i] = in[2 * i] >> 16;  // left = processed voice
    if (connected && frames == FRAME) {
      if (xQueueSend(micQ, &f, 0) != pdTRUE) statMicDrops++;
    }
  }
}

// ---------------------------------------------------------------- websocket
void onText(const uint8_t *payload, size_t len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  const char *type = doc["type"] | "";
  if (!strcmp(type, "play_end")) {
    PlayEnd pe{doc["id"] | 0u, wpos.load()};
    xQueueSend(endQ, &pe, 0);
  } else if (!strcmp(type, "stop")) {
    flushReq = true;
  } else if (!strcmp(type, "volume")) {
    gain = doc["gain"] | DEFAULT_GAIN;
    Serial.printf("[ws] gain = %.2f\n", gain.load());
  } else if (!strcmp(type, "state")) {
    Serial.printf("[ws] state: %s\n", (const char *)(doc["state"] | "?"));
  }
}

void onWsEvent(WStype_t type, uint8_t *payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED: {
      Serial.println("[ws] connected");
      ws.sendTXT("{\"type\":\"hello\",\"role\":\"audio\",\"device\":\"respeaker-lite\",\"rate\":16000}");
      xQueueReset(micQ);
      connected = true;
      digitalWrite(LED_BUILTIN, LOW);  // on (active low)
      break;
    }
    case WStype_DISCONNECTED:
      if (connected) Serial.println("[ws] disconnected");
      connected = false;
      flushReq = true;  // drop any half-played utterance
      xQueueReset(endQ);
      xQueueReset(doneQ);
      digitalWrite(LED_BUILTIN, HIGH);
      break;
    case WStype_BIN:
      if (len >= 2 && payload[0] == MSG_AUDIO) ringPushBytes(payload + 2, len - 2);
      break;
    case WStype_TEXT:
      onText(payload, len);
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== skeleton audio device (ReSpeaker Lite) ===");
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);

  ringSize = RATE * 15;  // 15 s of buffer
  ring = psramFound() ? (int16_t *)ps_malloc(ringSize * 2) : nullptr;
  if (!ring) {
    ringSize = RATE * 3;  // fall back to 3 s in internal RAM
    ring = (int16_t *)malloc(ringSize * 2);
  }
  Serial.printf("ring buffer: %u s (%s)\n", ringSize / RATE, psramFound() ? "PSRAM" : "internal RAM");

  endQ = xQueueCreate(8, sizeof(PlayEnd));
  doneQ = xQueueCreate(8, sizeof(PlayDone));
  micQ = xQueueCreate(25, sizeof(MicFrame));  // 500 ms

  i2sInit();
  xTaskCreatePinnedToCore(playbackTask, "play", 4096, nullptr, 5, nullptr, 1);
  xTaskCreatePinnedToCore(micTask, "mic", 4096, nullptr, 5, nullptr, 1);

  net::wifiBegin(Serial, "skeleton-audio");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);  // up to 10 s

  net::wsBegin(ws);
  ws.onEvent(onWsEvent);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  net::wifiService();
  net::wsWatch(connected);
  ws.loop();

  MicFrame f;
  while (connected && xQueueReceive(micQ, &f, 0) == pdTRUE) {
    ws.sendBIN((uint8_t *)f.s, sizeof(f.s));
    statMicSent++;
  }

  PlayDone d;
  while (xQueuePeek(doneQ, &d, 0) == pdTRUE && (int32_t)(millis() - d.dueMs) >= 0) {
    xQueueReceive(doneQ, &d, 0);
    char msg[64];
    snprintf(msg, sizeof(msg), "{\"type\":\"playback_done\",\"id\":%u}", (unsigned)d.id);
    ws.sendTXT(msg);
  }

  static uint32_t lastStats = 0;
  if (millis() - lastStats > 30000) {
    lastStats = millis();
    Serial.printf("[stats] wifi=%s(%s) rssi=%d ws=%s mic_sent=%u mic_drops=%u underruns=%u ring_drops=%u\n",
                  WiFi.status() == WL_CONNECTED ? "up" : "down", net::ssid(), WiFi.RSSI(), connected ? "up" : "down",
                  (unsigned)statMicSent.load(), (unsigned)statMicDrops.load(),
                  (unsigned)statUnderruns.load(), (unsigned)statRingDrops.load());
  }
  delay(1);
}
