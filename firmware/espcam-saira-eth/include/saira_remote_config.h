#pragma once

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>

#include "saira_config.h"
#include "saira_net.h"
#include "saira_ota.h"  // reuse URL parsing + join

using SairaApplyConfigFn = bool (*)(const String& key, const String& value);

static inline String _sairaDefaultRemoteConfigUrl(const String& serverBase) {
  return sairaJoinPath(serverBase, String("/device/") + SAIRA_DEVICE_ID + "/config.txt");
}

static inline bool sairaMaybeFetchRemoteConfig(const String& serverBase, SairaApplyConfigFn applyFn) {
  if (SAIRA_REMOTE_CONFIG_ENABLED == 0) return false;
  if (!applyFn) return false;
  if (!sairaNetConnected()) return false;

  static uint32_t nextCheckAt = 0;
  const uint32_t now = millis();
  if (nextCheckAt != 0 && (int32_t)(now - nextCheckAt) < 0) return false;
  nextCheckAt = now + (uint32_t)SAIRA_REMOTE_CONFIG_CHECK_INTERVAL_MS;

  String url = String(SAIRA_REMOTE_CONFIG_URL);
  url.trim();
  if (!url.length()) url = _sairaDefaultRemoteConfigUrl(serverBase);

  SairaParsedUrl u = sairaParseHttpUrl(url);
  if (!u.ok) {
    Serial.println("CFG: URL invalida.");
    return false;
  }

  static String etag;
  static const char* hdrKeys[] = {"ETag"};

  HTTPClient http;
  http.collectHeaders(hdrKeys, 1);
  http.setTimeout(8000);
  if (etag.length()) {
    http.addHeader("If-None-Match", etag);
  }

  int code = -1;
  String body;
  String gotEtag;

  if (u.https) {
    WiFiClientSecure client;
    if (SAIRA_TLS_INSECURE) client.setInsecure();
    if (!http.begin(client, url)) {
      Serial.println("CFG: http.begin() falhou.");
      return false;
    }
    code = http.GET();
    if (code == 200) {
      body = http.getString();
      gotEtag = http.header("ETag");
    }
    http.end();
  } else {
    WiFiClient client;
    if (!http.begin(client, url)) {
      Serial.println("CFG: http.begin() falhou.");
      return false;
    }
    code = http.GET();
    if (code == 200) {
      body = http.getString();
      gotEtag = http.header("ETag");
    }
    http.end();
  }

  if (code == 304) return false;
  if (code != 200) {
    Serial.print("CFG: GET falhou: ");
    Serial.println(code);
    return false;
  }

  gotEtag.trim();
  if (gotEtag.length()) etag = gotEtag;

  bool changed = false;
  int start = 0;
  while (start < (int)body.length()) {
    int end = body.indexOf('\n', start);
    if (end < 0) end = body.length();
    String line = body.substring(start, end);
    start = end + 1;
    line.trim();
    if (!line.length()) continue;
    if (line.startsWith("#")) continue;

    int eq = line.indexOf('=');
    if (eq <= 0) continue;
    String key = line.substring(0, eq);
    String val = line.substring(eq + 1);
    key.trim();
    val.trim();
    if (!key.length()) continue;

    if (applyFn(key, val)) changed = true;
  }

  return changed;
}
