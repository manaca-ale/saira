#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include "saira_config.h"

#if SAIRA_USE_ETHERNET
#include <ETH.h>
#endif

static inline bool sairaNetConnected() {
#if SAIRA_USE_ETHERNET
#if SAIRA_ETH_WIFI_DUAL_MODE
  // In dual mode, OTA/remote-config must depend on internet uplink (Wi-Fi).
  return WiFi.status() == WL_CONNECTED;
#else
  if (ETH.linkUp()) return true;
#if SAIRA_ETH_WIFI_FALLBACK
  return WiFi.status() == WL_CONNECTED;
#else
  return false;
#endif
#endif
#else
  return WiFi.status() == WL_CONNECTED;
#endif
}

static inline IPAddress sairaNetLocalIP() {
#if SAIRA_USE_ETHERNET
#if SAIRA_ETH_WIFI_DUAL_MODE
  if (WiFi.status() == WL_CONNECTED) return WiFi.localIP();
  if (ETH.linkUp()) return ETH.localIP();
  return IPAddress((uint32_t)0);
#else
  if (ETH.linkUp()) return ETH.localIP();
#if SAIRA_ETH_WIFI_FALLBACK
  if (WiFi.status() == WL_CONNECTED) return WiFi.localIP();
#endif
  return IPAddress((uint32_t)0);
#endif
#else
  return WiFi.localIP();
#endif
}

static inline const char* sairaNetKind() {
#if SAIRA_USE_ETHERNET
#if SAIRA_ETH_WIFI_DUAL_MODE
  if (WiFi.status() == WL_CONNECTED) return "wifi";
  if (ETH.linkUp()) return "eth";
  return "none";
#else
  if (ETH.linkUp()) return "eth";
#if SAIRA_ETH_WIFI_FALLBACK
  if (WiFi.status() == WL_CONNECTED) return "wifi";
#endif
  return "none";
#endif
#else
  return "wifi";
#endif
}
