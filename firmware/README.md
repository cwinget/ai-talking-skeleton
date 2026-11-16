# Firmware

All three are [PlatformIO](https://platformio.org/) projects (pioarduino platform, Arduino core 3.x).
Setup, configuration and flashing: [`docs/FIRMWARE.md`](../docs/FIRMWARE.md).

| Folder | Board | Role |
|---|---|---|
| [`body/`](body/) | ESP32-S3-CAM (N16R8, OV3660) | `body`: radar presence, camera, eye + mouth LEDs, jaw servo, Wi-Fi log on port 23 |
| [`audio/`](audio/) | Seeed ReSpeaker Lite (XIAO ESP32-S3) | `audio`: noise-suppressed mic up, speaker down |
| [`respeaker-test/`](respeaker-test/) | ReSpeaker Lite | standalone mic/speaker test, no server needed |

`include/skeleton_net.h` (Wi-Fi priority list + WebSocket connect) and `include/server_ca.h`
(trusted root certificates) are identical copies in `body/` and `audio/`; change both.
Each board needs its own `include/config.h`, copied from `config.example.h`. It holds your
Wi-Fi passwords and device token and is git-ignored: never commit it.
