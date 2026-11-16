// Talking Skeleton: BODY device firmware for the ESP32-S3-CAM (N16R8, OV3660).
//
// Implements the "body" role of PROTOCOL.md:
//   radar  : LD2410C OUT pin -> presence {present} to the server
//   camera : on {capture,count,interval_ms} -> JPEG frames as {image,seq,jpeg_b64}
//   mouth  : server [0x02][env] 50x/s -> jaw servo + mouth LED (smoothed)
//   eyes   : green (family) or red (scary) LEDs; idle glow, brighten with the voice
//   leds   : eye/mouth brightness set live from the server (led_config), saved in flash
//
// On boot it runs a short self-test (eyes, mouth LED, jaw sweep) so you can
// check the wiring before anything talks to the server.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <Preferences.h>
#include <mbedtls/base64.h>
#include <ESPmDNS.h>

#include "config.h"

// ---------------------------------------------------------------- network log
// Everything printed to the serial monitor is also sent to a TCP client on port 23,
// so you can watch the log over Wi-Fi with the box on its own power:
//     nc skeleton-body.local 23        (or nc <board-ip> 23)
WiFiServer logServer(23);
WiFiClient logClient;
SemaphoreHandle_t logLock;

class TeeLog : public Print {
 public:
  size_t write(uint8_t c) override { return write(&c, 1); }
  size_t write(const uint8_t *b, size_t n) override {
    Serial.write(b, n);
    if (logLock && xSemaphoreTake(logLock, pdMS_TO_TICKS(20)) == pdTRUE) {
      if (logClient && logClient.connected()) logClient.write(b, n);
      xSemaphoreGive(logLock);
    }
    return n;
  }
};
TeeLog Log;

#include "skeleton_net.h"  // Wi-Fi list + wss/token setup (after Log so it can log through it)

// Defaults for settings added after the first release (so older config.h files still build).
#ifndef RADAR_DEBUG
#define RADAR_DEBUG 1        // print radar status to the serial monitor
#endif
#ifndef RADAR_RX_PIN
#define RADAR_RX_PIN 41      // radar TX -> this pin for distance/energy readings; -1 = not wired
#endif
#ifndef RADAR_PRESENCE_SOURCE
#define RADAR_PRESENCE_SOURCE 2  // 0 = OUT pin only, 1 = radar TX data only, 2 = either
#endif
#ifndef RADAR_MAX_CM
#define RADAR_MAX_CM 0           // TX data only counts targets closer than this (0 = any distance)
#endif
#ifndef EYES_BRIGHTNESS
#define EYES_BRIGHTNESS 1.0  // 0..1 max eye brightness (perceptual); live-tunable with led_config
#endif
#ifndef MOUTH_BRIGHTNESS
#define MOUTH_BRIGHTNESS 1.0 // 0..1 max mouth LED brightness
#endif

// ---------------------------------------------------------------- camera pins (board pinout)
#define CAM_PIN_XCLK 15
#define CAM_PIN_SIOD 4
#define CAM_PIN_SIOC 5
#define CAM_PIN_D7 16  // Y9
#define CAM_PIN_D6 17  // Y8
#define CAM_PIN_D5 18  // Y7
#define CAM_PIN_D4 12  // Y6
#define CAM_PIN_D3 10  // Y5
#define CAM_PIN_D2 8   // Y4
#define CAM_PIN_D1 9   // Y3
#define CAM_PIN_D0 11  // Y2
#define CAM_PIN_VSYNC 6
#define CAM_PIN_HREF 7
#define CAM_PIN_PCLK 13

constexpr int PIN_STATUS_RGB = 48;  // on-board RGB LED
constexpr uint8_t MSG_MOUTH = 0x02;

// ---------------------------------------------------------------- state
WebSocketsClient ws;
bool connected = false;
bool cameraOk = false;
String convState = "idle";  // idle | greeting | listening | speaking
String mode = "family";     // family | scary

volatile int mouthTarget = 0;  // 0..255 from the server
volatile uint32_t lastMouthMs = 0;
float jaw = 0;                 // smoothed 0..255
bool servoActive = false;

// Jaw calibration: starts from config.h, overridden by values saved in flash
// (set live from the server with jaw_config; see PROTOCOL.md).
Preferences prefs;
float jawClosed = JAW_CLOSED_DEG;
float jawOpen = JAW_OPEN_DEG;

// Calibration test motion (overrides the voice-driven jaw while active)
enum JawTestMode : uint8_t { JT_NONE, JT_SWEEP, JT_HOLD };
struct {
  JawTestMode mode = JT_NONE;
  uint32_t startMs = 0, durMs = 0;
  float holdDeg = 0;
} jawTest;
constexpr uint32_t SWEEP_PERIOD_MS = 1200;  // one closed -> open -> closed cycle
uint32_t servoQuietSince = 0;

// LED brightness: 0..1 scale on top of the animation, starts from config.h,
// overridden by values saved in flash (set live from the server with led_config).
float eyeScale = EYES_BRIGHTNESS;
float mouthScale = MOUTH_BRIGHTNESS;

// LED test: hold the eyes and/or mouth at a fixed brightness for a while
enum LedTarget : uint8_t { LT_EYES = 1, LT_MOUTH = 2, LT_BOTH = 3 };
struct {
  bool active = false;
  uint8_t target = LT_BOTH;
  float level = 1.f;   // 0..1
  bool scaled = false; // true: level is multiplied by the saved brightness (preview)
  uint32_t untilMs = 0;
} ledTest;

bool presence = false;         // debounced radar state
bool rawPrev = false;
uint32_t rawSince = 0;

struct CaptureReq {
  int count;
  int intervalMs;
};
struct OutMsg {
  char *data;
  size_t len;
};
QueueHandle_t captureQ, outQ;

// ---------------------------------------------------------------- outputs
constexpr uint8_t LED_BITS = 12;  // 12-bit PWM so dim levels don't round down to off
constexpr float LED_MAX = (1 << LED_BITS) - 1;

void ledInit() {
  ledcAttach(PIN_EYES_RED, 5000, LED_BITS);
  ledcAttach(PIN_EYES_GREEN, 5000, LED_BITS);
  ledcAttach(PIN_MOUTH_LED, 5000, LED_BITS);
  ledcAttach(PIN_SERVO, 50, 14);  // 50 Hz servo frame, 14-bit duty
  ledcWrite(PIN_SERVO, 0);
}

uint32_t ledDuty(float x) {  // perceptual brightness 0..1 -> PWM duty
  x = constrain(x, 0.f, 1.f);
  return (uint32_t)(x * x * LED_MAX + 0.5f);
}

void setEyesRaw(float level) {  // level 0..1, NOT scaled by eyeScale
  bool green = FAMILY_EYES_GREEN && mode == "family";
  ledcWrite(PIN_EYES_GREEN, green ? ledDuty(level) : 0);
  ledcWrite(PIN_EYES_RED, green ? 0 : ledDuty(level));
}
void setEyes(float level) { setEyesRaw(level * eyeScale); }
void setMouthLedRaw(float level) { ledcWrite(PIN_MOUTH_LED, ledDuty(level)); }
void setMouthLed(float level) { setMouthLedRaw(level * mouthScale); }

void servoDeg(float deg) {
  float us = 500.f + constrain(deg, 0.f, 180.f) / 180.f * 2000.f;  // 0.5..2.5 ms
  ledcWrite(PIN_SERVO, (uint32_t)(us * 16383.f / 20000.f));
}

void servoOff() { ledcWrite(PIN_SERVO, 0); }  // no pulses: servo goes limp and quiet

void statusRgb(uint8_t r, uint8_t g, uint8_t b) { rgbLedWrite(PIN_STATUS_RGB, r, g, b); }

// ---------------------------------------------------------------- self-test
void selfTest() {
  Log.printf("self-test: red eyes (brightness %.2f)\n", eyeScale);
  ledcWrite(PIN_EYES_RED, ledDuty(eyeScale));
  delay(600);
  ledcWrite(PIN_EYES_RED, 0);
  Log.println("self-test: green eyes");
  ledcWrite(PIN_EYES_GREEN, ledDuty(eyeScale));
  delay(600);
  ledcWrite(PIN_EYES_GREEN, 0);
  Log.printf("self-test: mouth LED (brightness %.2f)\n", mouthScale);
  ledcWrite(PIN_MOUTH_LED, ledDuty(mouthScale));
  delay(600);
  ledcWrite(PIN_MOUTH_LED, 0);
  Log.printf("self-test: jaw %.1f -> %.1f -> %.1f deg\n", jawClosed, jawOpen, jawClosed);
  for (int i = 0; i <= 20; i++) {
    servoDeg(jawClosed + (jawOpen - jawClosed) * i / 20.f);
    delay(30);
  }
  for (int i = 20; i >= 0; i--) {
    servoDeg(jawClosed + (jawOpen - jawClosed) * i / 20.f);
    delay(30);
  }
  delay(300);
  if (JAW_RELAX_WHEN_IDLE) servoOff();
}

// ---------------------------------------------------------------- animation (50 Hz)
void animate() {
  uint32_t now = millis();
  int target = (now - lastMouthMs < 300) ? mouthTarget : 0;  // close if the stream stops
  float a = target > jaw ? 0.6f : 0.25f;                     // open fast, close slower
  jaw += (target - jaw) * a;
  float j = jaw / 255.f;

  // LED test from the server overrides the animation for its target(s)
  bool testEyes = false, testMouth = false;
  if (ledTest.active) {
    if ((int32_t)(now - ledTest.untilMs) >= 0) {
      ledTest.active = false;
      Log.println("[leds] test done");
    } else {
      testEyes = ledTest.target & LT_EYES;
      testMouth = ledTest.target & LT_MOUTH;
    }
  }

  // mouth LED follows the jaw
  if (testMouth) {
    if (ledTest.scaled) setMouthLed(ledTest.level);
    else setMouthLedRaw(ledTest.level);
  } else {
    setMouthLed(j);
  }

  // jaw servo
  if (jawTest.mode != JT_NONE) {  // calibration motion from the server
    uint32_t t = now - jawTest.startMs;
    if (t >= jawTest.durMs) {
      jawTest.mode = JT_NONE;
      Log.println("[jaw] test motion done");
    } else {
      float deg = jawTest.holdDeg;
      if (jawTest.mode == JT_SWEEP) {
        float ph = (t % SWEEP_PERIOD_MS) / (float)SWEEP_PERIOD_MS;
        float tri = ph < 0.5f ? ph * 2.f : (1.f - ph) * 2.f;
        deg = jawClosed + (jawOpen - jawClosed) * tri;
      }
      servoDeg(deg);
      servoActive = true;
      servoQuietSince = now;
    }
  } else if (jaw > 3 || !JAW_RELAX_WHEN_IDLE) {
    servoDeg(jawClosed + (jawOpen - jawClosed) * j);
    servoActive = true;
    servoQuietSince = now;
  } else if (servoActive) {
    servoDeg(jawClosed);
    if (now - servoQuietSince > 600) {  // closed and settled: let it rest
      servoOff();
      servoActive = false;
    }
  }

  // eyes
  float eye;
  float t = now / 1000.f;
  if (convState == "speaking" || convState == "greeting") {
    eye = 0.55f + 0.45f * j;  // brighten with the voice
    if (mode == "scary") eye *= 0.85f + 0.15f * (random(100) / 100.f);  // ghostly flicker
  } else if (convState == "listening") {
    eye = 0.45f + 0.05f * sinf(t * 6.f);
  } else {  // idle: slow breathing glow
    eye = 0.12f + 0.08f * sinf(t * 2.f * PI * 0.25f);
  }
  if (testEyes) {
    if (ledTest.scaled) setEyes(ledTest.level);
    else setEyesRaw(ledTest.level);
  } else {
    setEyes(eye);
  }
}

// ---------------------------------------------------------------- radar
// OUT pin gives present/absent. If the radar's TX pin is wired to RADAR_RX_PIN we
// also parse its report frames (256000 baud) for distance and signal energy.
struct RadarInfo {
  uint8_t state = 0;  // 0 none, 1 moving, 2 still, 3 moving+still
  uint16_t movingCm = 0, stillCm = 0;
  uint8_t movingEnergy = 0, stillEnergy = 0;
  uint32_t atMs = 0;
  uint32_t frames = 0;
} radarInfo;

#if RADAR_RX_PIN >= 0
HardwareSerial RadarSerial(1);
uint8_t rbuf[64];
size_t rlen = 0;

void pollRadarUart() {
  static const uint8_t HEAD[4] = {0xF4, 0xF3, 0xF2, 0xF1};
  static const uint8_t TAIL[4] = {0xF8, 0xF7, 0xF6, 0xF5};
  while (RadarSerial.available()) {
    uint8_t b = RadarSerial.read();
    if (rlen < 4) {  // hunting for the frame header
      if (b == HEAD[rlen]) rbuf[rlen++] = b;
      else if (b == HEAD[0]) { rbuf[0] = b; rlen = 1; }
      else rlen = 0;
      continue;
    }
    rbuf[rlen++] = b;
    if (rlen < 6) continue;
    size_t dataLen = rbuf[4] | (rbuf[5] << 8);
    size_t total = 6 + dataLen + 4;
    if (dataLen < 11 || total > sizeof(rbuf)) { rlen = 0; continue; }  // not a report frame
    if (rlen < total) continue;
    if (!memcmp(rbuf + total - 4, TAIL, 4)) {
      // data: [type 0x02|0x01][0xAA][state][moving cm 2][moving energy][still cm 2][still energy]...
      const uint8_t *d = rbuf + 6;
      if ((d[0] == 0x01 || d[0] == 0x02) && d[1] == 0xAA) {
        radarInfo.state = d[2];
        radarInfo.movingCm = d[3] | (d[4] << 8);
        radarInfo.movingEnergy = d[5];
        radarInfo.stillCm = d[6] | (d[7] << 8);
        radarInfo.stillEnergy = d[8];
        radarInfo.atMs = millis();
        radarInfo.frames++;
      }
    }
    rlen = 0;
  }
}
#endif

void radarInit() {
  pinMode(PIN_RADAR, INPUT);
#if RADAR_RX_PIN >= 0
  RadarSerial.begin(256000, SERIAL_8N1, RADAR_RX_PIN, -1);
  Log.printf("[radar] OUT on GPIO%d, reading radar TX on GPIO%d\n", PIN_RADAR, RADAR_RX_PIN);
#else
  Log.printf("[radar] OUT on GPIO%d (TX not wired)\n", PIN_RADAR);
#endif
}

// Does the radar's TX data (fresh within 1 s) report a target in range?
bool radarUartSees() {
#if RADAR_RX_PIN >= 0
  if (radarInfo.frames == 0 || millis() - radarInfo.atMs > 1000) return false;
  uint8_t st = radarInfo.state & 3;
  if (!st) return false;
  if (RADAR_MAX_CM <= 0) return true;
  bool moving = (st & 1) && radarInfo.movingCm < RADAR_MAX_CM;
  bool still = (st & 2) && radarInfo.stillCm < RADAR_MAX_CM;
  return moving || still;
#else
  return false;
#endif
}

bool radarOutHigh() { return digitalRead(PIN_RADAR) == HIGH; }

// Presence decision before debouncing, from the sources chosen by RADAR_PRESENCE_SOURCE.
bool radarRaw() {
  switch (RADAR_PRESENCE_SOURCE) {
    case 0: return radarOutHigh();
    case 1: return radarUartSees();
    default: return radarOutHigh() || radarUartSees();
  }
}

void radarDebug(bool raw) {
#if RADAR_DEBUG
  static uint32_t last = 0;
  uint32_t now = millis();
  if (now - last < 500) return;
  last = now;
  char detail[128] = "";
#if RADAR_RX_PIN >= 0
  static const char *states[] = {"nothing", "MOVING", "STILL", "MOVING+STILL"};
  if (radarInfo.frames == 0 || now - radarInfo.atMs > 2000) {
    snprintf(detail, sizeof(detail), " | no data on GPIO%d (radar TX wired? %u frames so far)",
             RADAR_RX_PIN, (unsigned)radarInfo.frames);
  } else {
    snprintf(detail, sizeof(detail), " | sees %s: moving %ucm (energy %u), still %ucm (energy %u)",
             states[radarInfo.state & 3], radarInfo.movingCm, radarInfo.movingEnergy,
             radarInfo.stillCm, radarInfo.stillEnergy);
  }
#endif
  Log.printf("[radar] OUT=%s TX=%s -> %s%s\n", radarOutHigh() ? "HIGH" : "low ",
             radarUartSees() ? "yes" : "no ", presence ? "PRESENT" : "nobody", detail);
#endif
}

void pollRadar() {
#if RADAR_RX_PIN >= 0
  pollRadarUart();
#endif
  bool raw = radarRaw();
  uint32_t now = millis();
  if (raw != rawPrev) {
    rawPrev = raw;
    rawSince = now;
    if (RADAR_DEBUG)
      Log.printf("[radar] %s (OUT=%s, TX=%s)\n", raw ? "target" : "no target",
                 radarOutHigh() ? "HIGH" : "low", radarUartSees() ? "yes" : "no");
  }
  uint32_t need = raw ? 250 : 2000;  // quick to notice, slow to give up
  if (raw != presence && now - rawSince >= need) {
    presence = raw;
    Log.printf("[radar] => %s%s\n", presence ? "PRESENT" : "gone",
                  connected ? " (sent to server)" : " (NOT sent: not connected to server)");
    if (connected) {
      char msg[48];
      snprintf(msg, sizeof(msg), "{\"type\":\"presence\",\"present\":%s}", presence ? "true" : "false");
      ws.sendTXT(msg);
    }
  }
  radarDebug(raw);
}

// ---------------------------------------------------------------- camera
bool cameraInit() {
  camera_config_t c = {};
  c.pin_pwdn = -1;
  c.pin_reset = -1;
  c.pin_xclk = CAM_PIN_XCLK;
  c.pin_sccb_sda = CAM_PIN_SIOD;
  c.pin_sccb_scl = CAM_PIN_SIOC;
  c.pin_d7 = CAM_PIN_D7;
  c.pin_d6 = CAM_PIN_D6;
  c.pin_d5 = CAM_PIN_D5;
  c.pin_d4 = CAM_PIN_D4;
  c.pin_d3 = CAM_PIN_D3;
  c.pin_d2 = CAM_PIN_D2;
  c.pin_d1 = CAM_PIN_D1;
  c.pin_d0 = CAM_PIN_D0;
  c.pin_vsync = CAM_PIN_VSYNC;
  c.pin_href = CAM_PIN_HREF;
  c.pin_pclk = CAM_PIN_PCLK;
  c.xclk_freq_hz = 20000000;
  c.ledc_timer = LEDC_TIMER_3;      // keep clear of the LED/servo timers
  c.ledc_channel = LEDC_CHANNEL_7;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_VGA;     // 640x480: plenty for costumes, small to send
  c.jpeg_quality = 12;
  c.fb_count = 1;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;  // capture only when asked (no FB-OVF warnings)
  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Log.printf("[camera] init failed: 0x%x (continuing without camera)\n", err);
    return false;
  }
  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, CAM_VFLIP);
  s->set_hmirror(s, CAM_HMIRROR);
  Log.printf("[camera] ok, sensor PID 0x%x\n", s->id.PID);
  return true;
}

void captureTask(void *) {
  CaptureReq req;
  for (;;) {
    if (xQueueReceive(captureQ, &req, portMAX_DELAY) != pdTRUE) continue;
    if (!cameraOk) continue;
    camera_fb_t *stale = esp_camera_fb_get();  // drop a possibly old frame
    if (stale) esp_camera_fb_return(stale);
    for (int i = 0; i < req.count; i++) {
      camera_fb_t *fb = esp_camera_fb_get();
      if (!fb) {
        Log.println("[camera] capture failed");
        continue;
      }
      // {"type":"image","seq":N,"jpeg_b64":"...."}
      size_t b64len = 4 * ((fb->len + 2) / 3);
      size_t cap = b64len + 64;
      char *msg = (char *)ps_malloc(cap + 1);
      if (msg) {
        int head = snprintf(msg, 64, "{\"type\":\"image\",\"seq\":%d,\"jpeg_b64\":\"", i);
        size_t olen = 0;
        mbedtls_base64_encode((unsigned char *)msg + head, cap - head, &olen, fb->buf, fb->len);
        size_t len = head + olen;
        msg[len++] = '"';
        msg[len++] = '}';
        msg[len] = 0;
        OutMsg out{msg, len};
        if (xQueueSend(outQ, &out, 0) != pdTRUE) free(msg);
      }
      Log.printf("[camera] frame %d: %u bytes\n", i, (unsigned)fb->len);
      esp_camera_fb_return(fb);
      if (i + 1 < req.count) vTaskDelay(pdMS_TO_TICKS(req.intervalMs));
    }
  }
}

// ---------------------------------------------------------------- websocket
void loadJawConfig() {
  prefs.begin("jaw", true);
  jawClosed = prefs.getFloat("closed", JAW_CLOSED_DEG);
  jawOpen = prefs.getFloat("open", JAW_OPEN_DEG);
  bool saved = prefs.isKey("closed");
  prefs.end();
  Log.printf("[jaw] closed %.1f, open %.1f (%s)\n", jawClosed, jawOpen,
                saved ? "saved in flash" : "config.h defaults");
}

void saveJawConfig() {
  prefs.begin("jaw", false);
  prefs.putFloat("closed", jawClosed);
  prefs.putFloat("open", jawOpen);
  prefs.end();
}

void clearJawConfig() {
  prefs.begin("jaw", false);
  prefs.clear();
  prefs.end();
  jawClosed = JAW_CLOSED_DEG;
  jawOpen = JAW_OPEN_DEG;
}

void sendJawConfig(bool saved) {
  char msg[128];
  snprintf(msg, sizeof(msg),
           "{\"type\":\"jaw_config\",\"closed\":%.1f,\"open\":%.1f,\"saved\":%s}",
           jawClosed, jawOpen, saved ? "true" : "false");
  ws.sendTXT(msg);
}

void loadLedConfig() {
  prefs.begin("leds", true);
  eyeScale = prefs.getFloat("eyes", EYES_BRIGHTNESS);
  mouthScale = prefs.getFloat("mouth", MOUTH_BRIGHTNESS);
  bool saved = prefs.isKey("eyes");
  prefs.end();
  eyeScale = constrain(eyeScale, 0.f, 1.f);
  mouthScale = constrain(mouthScale, 0.f, 1.f);
  Log.printf("[leds] eyes %.2f, mouth %.2f (%s)\n", eyeScale, mouthScale,
             saved ? "saved in flash" : "config.h defaults");
}

void saveLedConfig() {
  prefs.begin("leds", false);
  prefs.putFloat("eyes", eyeScale);
  prefs.putFloat("mouth", mouthScale);
  prefs.end();
}

void clearLedConfig() {
  prefs.begin("leds", false);
  prefs.clear();
  prefs.end();
  eyeScale = EYES_BRIGHTNESS;
  mouthScale = MOUTH_BRIGHTNESS;
}

bool ledConfigSaved() {
  prefs.begin("leds", true);
  bool saved = prefs.isKey("eyes");
  prefs.end();
  return saved;
}

void sendLedConfig(bool saved) {
  char msg[128];
  snprintf(msg, sizeof(msg), "{\"type\":\"led_config\",\"eyes\":%.3f,\"mouth\":%.3f,\"saved\":%s}",
           eyeScale, mouthScale, saved ? "true" : "false");
  ws.sendTXT(msg);
}

void startLedTest(uint8_t target, float level, uint32_t ms, bool scaled) {
  ledTest.target = target;
  ledTest.level = constrain(level, 0.f, 1.f);
  ledTest.scaled = scaled;
  ledTest.untilMs = millis() + ms;
  ledTest.active = true;
}

uint8_t parseLedTarget(const char *s) {
  if (!strcmp(s, "eyes")) return LT_EYES;
  if (!strcmp(s, "mouth")) return LT_MOUTH;
  return LT_BOTH;
}

void startJawTest(JawTestMode mode, uint32_t durMs, float holdDeg = 0) {
  jawTest.mode = mode;
  jawTest.startMs = millis();
  jawTest.durMs = durMs;
  jawTest.holdDeg = constrain(holdDeg, 0.f, 180.f);
}

void onText(const uint8_t *payload, size_t len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  const char *type = doc["type"] | "";
  if (!strcmp(type, "state")) {
    convState = (const char *)(doc["state"] | "idle");
    if (doc["mode"].is<const char *>()) mode = (const char *)doc["mode"];
    Log.printf("[ws] state: %s (%s)\n", convState.c_str(), mode.c_str());
  } else if (!strcmp(type, "mode")) {
    mode = (const char *)(doc["mode"] | "family");
    Log.printf("[ws] mode: %s\n", mode.c_str());
  } else if (!strcmp(type, "jaw_config")) {
    // {"type":"jaw_config","closed":92,"open":118,"save":true}  (either angle optional)
    if (doc["reset"] | false) {
      clearJawConfig();
      Log.println("[jaw] reset to config.h defaults");
      sendJawConfig(false);
    } else {
      if (!doc["closed"].isNull()) jawClosed = constrain(doc["closed"].as<float>(), 0.f, 180.f);
      if (!doc["open"].isNull()) jawOpen = constrain(doc["open"].as<float>(), 0.f, 180.f);
      bool save = doc["save"] | true;
      if (save) saveJawConfig();
      Log.printf("[jaw] set closed %.1f, open %.1f%s\n", jawClosed, jawOpen, save ? " (saved)" : "");
      startJawTest(JT_SWEEP, SWEEP_PERIOD_MS);  // show the new range once
      sendJawConfig(save);
    }
  } else if (!strcmp(type, "jaw_test")) {
    // {"type":"jaw_test","action":"sweep","count":3}
    // {"type":"jaw_test","action":"hold","deg":100,"ms":3000}
    // {"type":"jaw_test","action":"open"|"closed","ms":3000}
    const char *action = doc["action"] | "sweep";
    uint32_t ms = doc["ms"] | 3000;
    if (!strcmp(action, "sweep")) {
      int count = constrain((int)(doc["count"] | 3), 1, 20);
      startJawTest(JT_SWEEP, count * SWEEP_PERIOD_MS);
    } else if (!strcmp(action, "hold")) {
      startJawTest(JT_HOLD, ms, doc["deg"] | jawClosed);
    } else if (!strcmp(action, "open")) {
      startJawTest(JT_HOLD, ms, jawOpen);
    } else if (!strcmp(action, "closed")) {
      startJawTest(JT_HOLD, ms, jawClosed);
    }
    Log.printf("[jaw] test: %s\n", action);
    sendJawConfig(true);  // acknowledge with the current values
  } else if (!strcmp(type, "jaw_get")) {
    prefs.begin("jaw", true);
    bool saved = prefs.isKey("closed");
    prefs.end();
    sendJawConfig(saved);
  } else if (!strcmp(type, "led_config")) {
    // {"type":"led_config","eyes":0.4,"mouth":0.6,"save":true}  (either optional)
    // {"type":"led_config","reset":true}
    if (doc["reset"] | false) {
      clearLedConfig();
      Log.println("[leds] reset to config.h defaults");
      startLedTest(LT_BOTH, 1.f, 1500, true);
      sendLedConfig(false);
    } else {
      uint8_t changed = 0;
      if (!doc["eyes"].isNull()) {
        eyeScale = constrain(doc["eyes"].as<float>(), 0.f, 1.f);
        changed |= LT_EYES;
      }
      if (!doc["mouth"].isNull()) {
        mouthScale = constrain(doc["mouth"].as<float>(), 0.f, 1.f);
        changed |= LT_MOUTH;
      }
      bool save = doc["save"] | true;
      if (save) saveLedConfig();
      Log.printf("[leds] set eyes %.2f, mouth %.2f%s\n", eyeScale, mouthScale, save ? " (saved)" : "");
      if (changed) startLedTest(changed, 1.f, 1500, true);  // show the new max for 1.5 s
      sendLedConfig(save || ledConfigSaved());
    }
  } else if (!strcmp(type, "led_test")) {
    // {"type":"led_test","target":"eyes"|"mouth"|"both","level":0.5,"ms":3000}
    // level is absolute (ignores the saved brightness): use it to find a value you like.
    // {"type":"led_test","action":"stop"} ends a running test.
    const char *action = doc["action"] | "hold";
    if (!strcmp(action, "stop")) {
      ledTest.active = false;
      Log.println("[leds] test stopped");
    } else {
      uint8_t target = parseLedTarget(doc["target"] | "both");
      float level = doc["level"] | 1.0f;
      uint32_t ms = constrain((uint32_t)(doc["ms"] | 3000), 100u, 60000u);
      startLedTest(target, level, ms, false);
      Log.printf("[leds] test: %s at %.2f for %u ms\n", doc["target"] | "both", level, (unsigned)ms);
    }
    sendLedConfig(ledConfigSaved());
  } else if (!strcmp(type, "led_get")) {
    sendLedConfig(ledConfigSaved());
  } else if (!strcmp(type, "capture")) {
    CaptureReq req{doc["count"] | 3, doc["interval_ms"] | 500};
    xQueueSend(captureQ, &req, 0);
  }
}

void onWsEvent(WStype_t type, uint8_t *payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      Log.println("[ws] connected");
      ws.sendTXT("{\"type\":\"hello\",\"role\":\"body\",\"device\":\"skeleton-body\"}");
      connected = true;
      break;
    case WStype_DISCONNECTED:
      if (connected) Log.println("[ws] disconnected");
      connected = false;
      convState = "idle";
      mouthTarget = 0;
      break;
    case WStype_BIN:
      if (len >= 2 && payload[0] == MSG_MOUTH) {
        mouthTarget = payload[1];
        lastMouthMs = millis();
      }
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
  logLock = xSemaphoreCreateMutex();
  delay(500);
  Log.println("\n=== skeleton body (ESP32-S3-CAM) ===");
  radarInit();
  ledInit();
  statusRgb(20, 0, 0);
  loadJawConfig();
  loadLedConfig();
  selfTest();

  captureQ = xQueueCreate(2, sizeof(CaptureReq));
  outQ = xQueueCreate(6, sizeof(OutMsg));
  cameraOk = psramFound() && cameraInit();
  if (!psramFound()) Log.println("[camera] no PSRAM found: camera disabled");
  xTaskCreatePinnedToCore(captureTask, "capture", 6144, nullptr, 3, nullptr, 1);

  WiFi.onEvent([](WiFiEvent_t e, WiFiEventInfo_t info) {
    if (e == ARDUINO_EVENT_WIFI_STA_DISCONNECTED)
      Log.printf("[wifi] disconnected, reason %d\n", info.wifi_sta_disconnected.reason);
  });
  net::wifiBegin(Log, "skeleton-body");

  logServer.begin();
  logServer.setNoDelay(true);

  net::wsBegin(ws);
  ws.onEvent(onWsEvent);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(15000, 3000, 2);
}

void pollLogClient() {
  static bool mdnsUp = false;
  if (!mdnsUp && WiFi.status() == WL_CONNECTED) {
    mdnsUp = MDNS.begin("skeleton-body");
    if (mdnsUp) MDNS.addService("telnet", "tcp", 23);
  }
  if (logServer.hasClient()) {
    WiFiClient c = logServer.accept();
    xSemaphoreTake(logLock, portMAX_DELAY);
    if (logClient) logClient.stop();  // one viewer at a time; newest wins
    logClient = c;
    logClient.setNoDelay(true);
    xSemaphoreGive(logLock);
    Log.printf("\n=== skeleton-body log (wifi %s, ip %s, rssi %d, server %s, radar OUT=%s, %s) ===\n",
               WiFi.SSID().c_str(), WiFi.localIP().toString().c_str(), WiFi.RSSI(),
               connected ? "connected" : "NOT connected",
               digitalRead(PIN_RADAR) ? "HIGH" : "low", presence ? "PRESENT" : "nobody");
  }
}

void loop() {
  net::wifiService();
  net::wsWatch(connected);
  pollLogClient();
  ws.loop();
  pollRadar();

  OutMsg out;
  while (xQueueReceive(outQ, &out, 0) == pdTRUE) {
    if (connected) ws.sendTXT((uint8_t *)out.data, out.len);
    free(out.data);
  }

  static uint32_t lastAnim = 0;
  if (millis() - lastAnim >= 20) {
    lastAnim = millis();
    animate();
  }

  // on-board status light: red = no Wi-Fi, yellow = Wi-Fi but no server,
  // green = connected; blue while the radar sees someone
  static uint32_t lastRgb = 0;
  if (millis() - lastRgb >= 200) {
    lastRgb = millis();
    if (presence) statusRgb(0, 0, 25);
    else if (connected) statusRgb(0, 12, 0);
    else if (WiFi.status() == WL_CONNECTED) statusRgb(15, 10, 0);
    else statusRgb(20, 0, 0);
  }
  delay(1);
}
