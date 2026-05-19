#pragma once

#include <Arduino.h>
#include <HTTPClient.h>
#include <HTTPUpdate.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>

#include "saira_config.h"
#include "saira_net.h"

struct SairaParsedUrl {
  bool ok = false;
  bool https = false;
  String host;
  uint16_t port = 0;
  String path;
};

static inline SairaParsedUrl sairaParseHttpUrl(const String& url) {
  SairaParsedUrl out;
  String s = url;
  s.trim();

  if (s.startsWith("https://")) {
    out.https = true;
    s.remove(0, 8);
  } else if (s.startsWith("http://")) {
    out.https = false;
    s.remove(0, 7);
  } else {
    return out;
  }

  int slash = s.indexOf('/');
  String hostPort = (slash >= 0) ? s.substring(0, slash) : s;
  out.path = (slash >= 0) ? s.substring(slash) : String("/");
  if (!out.path.startsWith("/")) out.path = "/" + out.path;

  int colon = hostPort.indexOf(':');
  if (colon >= 0) {
    out.host = hostPort.substring(0, colon);
    long p = hostPort.substring(colon + 1).toInt();
    if (p <= 0 || p > 65535) return SairaParsedUrl{};
    out.port = (uint16_t)p;
  } else {
    out.host = hostPort;
    out.port = out.https ? 443 : 80;
  }

  if (!out.host.length()) return SairaParsedUrl{};
  out.ok = true;
  return out;
}

static inline String sairaJoinPath(const String& base, const String& tail) {
  if (base.endsWith("/") && tail.startsWith("/")) return base + tail.substring(1);
  if (!base.endsWith("/") && !tail.startsWith("/")) return base + "/" + tail;
  return base + tail;
}

static inline bool sairaReadManifestKV(const String& body, const char* key, String& outVal) {
  // key=value\n
  String k = String(key) + "=";
  int idx = body.indexOf(k);
  if (idx < 0) return false;
  int start = idx + k.length();
  int end = body.indexOf('\n', start);
  if (end < 0) end = body.length();
  outVal = body.substring(start, end);
  outVal.trim();
  return true;
}

static inline String sairaResolveMaybeRelativeUrl(const String& baseUrl, const String& maybeUrl) {
  String u = maybeUrl;
  u.trim();
  if (u.startsWith("http://") || u.startsWith("https://")) return u;
  return sairaJoinPath(baseUrl, u);
}

static inline void sairaMaybeCheckOta() {
  if (SAIRA_OTA_ENABLED == 0) return;
  if (!sairaNetConnected()) return;

  static uint32_t nextCheckAt = 0;
  uint32_t now = millis();
  if (nextCheckAt != 0 && (int32_t)(now - nextCheckAt) < 0) return;
  nextCheckAt = now + (uint32_t)SAIRA_OTA_CHECK_INTERVAL_MS;

  String base = String(SAIRA_SERVER_BASE);
  String manifestUrl = String(SAIRA_OTA_MANIFEST_URL);
  if (manifestUrl.length() == 0) {
    manifestUrl = sairaJoinPath(base, "/ota/manifest.txt");
  }

  SairaParsedUrl mu = sairaParseHttpUrl(manifestUrl);
  if (!mu.ok) {
    Serial.println("OTA: manifest URL invalida.");
    return;
  }

  Serial.print("OTA: checando ");
  Serial.println(manifestUrl);

  String body;
  {
    HTTPClient http;
    http.setTimeout(8000);
    if (mu.https) {
      WiFiClientSecure client;
      if (SAIRA_TLS_INSECURE) client.setInsecure();
      if (!http.begin(client, manifestUrl)) {
        Serial.println("OTA: http.begin() falhou.");
        return;
      }
      if (String(SAIRA_OTA_ADMIN_TOKEN).length()) {
        http.addHeader("X-Admin-Token", SAIRA_OTA_ADMIN_TOKEN);
      }
      int code = http.GET();
      if (code != 200) {
        Serial.printf("OTA: manifest GET -> %d\n", code);
        http.end();
        return;
      }
      body = http.getString();
      http.end();
    } else {
      WiFiClient client;
      if (!http.begin(client, manifestUrl)) {
        Serial.println("OTA: http.begin() falhou.");
        return;
      }
      if (String(SAIRA_OTA_ADMIN_TOKEN).length()) {
        http.addHeader("X-Admin-Token", SAIRA_OTA_ADMIN_TOKEN);
      }
      int code = http.GET();
      if (code != 200) {
        Serial.printf("OTA: manifest GET -> %d\n", code);
        http.end();
        return;
      }
      body = http.getString();
      http.end();
    }
  }

  String version, binUrl;
  if (!sairaReadManifestKV(body, "version", version) || !sairaReadManifestKV(body, "bin_url", binUrl)) {
    Serial.println("OTA: manifest invalido (esperado version= e bin_url=).");
    return;
  }

  version.trim();
  binUrl.trim();
  if (!version.length() || !binUrl.length()) {
    Serial.println("OTA: manifest incompleto.");
    return;
  }

  String current = String(SAIRA_OTA_CURRENT_VERSION);
  if (version == current) {
    Serial.println("OTA: sem atualizacao.");
    return;
  }

  String resolvedBinUrl = sairaResolveMaybeRelativeUrl(base, binUrl);
  Serial.print("OTA: atualizando de ");
  Serial.println(resolvedBinUrl);

  t_httpUpdate_return ret;
  if (resolvedBinUrl.startsWith("https://")) {
    WiFiClientSecure client;
    if (SAIRA_TLS_INSECURE) client.setInsecure();
    ret = httpUpdate.update(client, resolvedBinUrl, current);
  } else {
    WiFiClient client;
    ret = httpUpdate.update(client, resolvedBinUrl, current);
  }

  switch (ret) {
    case HTTP_UPDATE_FAILED:
      Serial.printf("OTA: falhou (%d): %s\n", httpUpdate.getLastError(), httpUpdate.getLastErrorString().c_str());
      break;
    case HTTP_UPDATE_NO_UPDATES:
      Serial.println("OTA: sem updates (servidor).");
      break;
    case HTTP_UPDATE_OK:
      Serial.println("OTA: OK (reiniciando)...");
      break;
  }
}
