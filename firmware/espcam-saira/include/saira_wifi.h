#pragma once

#include <Arduino.h>
#include <WiFi.h>
#if defined(__has_include)
#if __has_include("esp32-hal-rgb-led.h")
#include "esp32-hal-rgb-led.h"
#define SAIRA_HAS_RGB_HAL 1
#endif
#endif

// Wi-Fi helper used by both firmwares.
// Goal: make connection more reliable on ESP32-CAM and provide actionable logs.

#if defined(RGB_BUILTIN) && defined(SAIRA_HAS_RGB_HAL)
static constexpr int SAIRA_WIFI_RGB_PIN = RGB_BUILTIN;
#define SAIRA_WIFI_RGB_AVAILABLE 1
#else
#define SAIRA_WIFI_RGB_AVAILABLE 0
#endif

#if defined(LED_BUILTIN)
static constexpr int SAIRA_WIFI_LED_PIN = LED_BUILTIN;
static constexpr int SAIRA_WIFI_LED_ON_LEVEL = HIGH;
static constexpr int SAIRA_WIFI_LED_OFF_LEVEL = LOW;
#define SAIRA_WIFI_LED_AVAILABLE 1
#else
static constexpr int SAIRA_WIFI_LED_PIN = -1;
#define SAIRA_WIFI_LED_AVAILABLE 0
#endif

static inline void sairaInitWifiLed() {
#if SAIRA_WIFI_RGB_AVAILABLE
  neopixelWrite(SAIRA_WIFI_RGB_PIN, 0, 0, 0);
#endif
#if SAIRA_WIFI_LED_AVAILABLE
  static bool initialized = false;
  if (initialized) return;
  initialized = true;
  pinMode(SAIRA_WIFI_LED_PIN, OUTPUT);
  digitalWrite(SAIRA_WIFI_LED_PIN, SAIRA_WIFI_LED_OFF_LEVEL);
#endif
}

static inline void sairaSetWifiLed(bool connected) {
#if SAIRA_WIFI_RGB_AVAILABLE
  if (connected) {
    // Green when Wi-Fi is connected.
    neopixelWrite(SAIRA_WIFI_RGB_PIN, 0, 255, 0);
  } else {
    neopixelWrite(SAIRA_WIFI_RGB_PIN, 0, 0, 0);
  }
#endif
#if SAIRA_WIFI_LED_AVAILABLE
  digitalWrite(SAIRA_WIFI_LED_PIN, connected ? SAIRA_WIFI_LED_ON_LEVEL : SAIRA_WIFI_LED_OFF_LEVEL);
#else
  (void)connected;
#endif
}

static inline void sairaLogWifiStatusOnce() {
  wl_status_t st = WiFi.status();
  Serial.print("WiFi status=");
  Serial.println((int)st);
}

static inline void sairaPrintWifiScan() {
  Serial.println("WiFi: escaneando redes...");
  int n = WiFi.scanNetworks(/*async*/ false, /*hidden*/ true);
  Serial.printf("WiFi: %d redes encontradas.\n", n);
  for (int i = 0; i < n && i < 10; i++) {
    Serial.printf("  %d) %s  RSSI=%d  CH=%d  ENC=%d\n",
                  i + 1,
                  WiFi.SSID(i).c_str(),
                  WiFi.RSSI(i),
                  WiFi.channel(i),
                  (int)WiFi.encryptionType(i));
  }
  WiFi.scanDelete();
}

static inline void sairaSetupWifiEventLogs() {
  static bool installed = false;
  if (installed) return;
  installed = true;

  WiFi.onEvent([](arduino_event_id_t event, arduino_event_info_t info) {
    Serial.print("WiFi event: ");
    Serial.println((int)event);

#if defined(ARDUINO_EVENT_WIFI_STA_DISCONNECTED)
    if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
      Serial.print("WiFi disconnected reason=");
      Serial.println((int)info.wifi_sta_disconnected.reason);
      sairaSetWifiLed(false);
    }
#endif
#if defined(ARDUINO_EVENT_WIFI_STA_GOT_IP)
    if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
      sairaSetWifiLed(true);
    }
#endif
  });
}

static inline bool sairaConnectWiFi(const char* ssid, const char* password, const char* hostname,
                                   uint32_t timeoutMs = 30000) {
  sairaInitWifiLed();
  sairaSetWifiLed(false);
  sairaSetupWifiEventLogs();

  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setSleep(false);         // Improves stability for some ESP32-CAM setups
  WiFi.setAutoReconnect(true);
  // Help marginal RSSI links.
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  if (hostname && *hostname) {
    WiFi.setHostname(hostname);
  }

  Serial.print("WiFi: SSID=");
  Serial.println(ssid ? ssid : "(null)");

  // Ensure we are not stuck with a previous static IP config.
  WiFi.disconnect(true /*wifioff*/, true /*eraseap*/);
  delay(200);
  WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE, INADDR_NONE);

  WiFi.begin(ssid, password);

  uint32_t start = millis();
  uint32_t lastDot = 0;
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    if (millis() - lastDot >= 500) {
      Serial.print(".");
      lastDot = millis();
    }
    delay(50);
  }

  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    sairaSetWifiLed(true);
    Serial.print("WiFi online. IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("WiFi gateway: ");
    Serial.println(WiFi.gatewayIP());
    Serial.print("WiFi DNS: ");
    Serial.println(WiFi.dnsIP());
    Serial.print("WiFi RSSI: ");
    Serial.println(WiFi.RSSI());
    return true;
  }

  Serial.println("WiFi: falha ao conectar (timeout).");
  sairaSetWifiLed(false);
  sairaLogWifiStatusOnce();
  sairaPrintWifiScan();
  return false;
}
