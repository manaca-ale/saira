#pragma once

#include <Arduino.h>
#include <Preferences.h>

#include "saira_config.h"

struct SairaRuntimeConfig {
  String deviceId;
  String wifiSsid;
  String wifiPassword;
};

static inline String sairaTrimmedNoNewlines(const String& in) {
  String out = in;
  out.replace("\r", "");
  out.replace("\n", "");
  out.trim();
  return out;
}

// Persisted runtime config lives in NVS and survives OTA updates.
// First boot after USB provisioning seeds values from build-time macros.
static inline SairaRuntimeConfig sairaLoadRuntimeConfig() {
  SairaRuntimeConfig cfg;
  cfg.deviceId = sairaTrimmedNoNewlines(String(SAIRA_DEVICE_ID));
  cfg.wifiSsid = sairaTrimmedNoNewlines(String(SAIRA_WIFI_SSID));
  cfg.wifiPassword = String(SAIRA_WIFI_PASSWORD);

  Preferences prefs;
  if (!prefs.begin("saira_cfg", false)) {
    return cfg;
  }

  String storedDeviceId = sairaTrimmedNoNewlines(prefs.getString("device_id", ""));
  String storedSsid = sairaTrimmedNoNewlines(prefs.getString("wifi_ssid", ""));
  String storedPass = prefs.getString("wifi_pass", "");

  if (!storedDeviceId.length()) {
    prefs.putString("device_id", cfg.deviceId);
    storedDeviceId = cfg.deviceId;
  }
  if (!storedSsid.length()) {
    prefs.putString("wifi_ssid", cfg.wifiSsid);
    storedSsid = cfg.wifiSsid;
  }
  // Keep empty password valid for open networks.
  if (!prefs.isKey("wifi_pass")) {
    prefs.putString("wifi_pass", cfg.wifiPassword);
    storedPass = cfg.wifiPassword;
  }

  prefs.end();

  if (storedDeviceId.length()) cfg.deviceId = storedDeviceId;
  if (storedSsid.length()) cfg.wifiSsid = storedSsid;
  cfg.wifiPassword = storedPass;
  return cfg;
}

