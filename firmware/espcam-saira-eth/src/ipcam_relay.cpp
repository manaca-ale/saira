#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "img_converters.h"
#include "mbedtls/base64.h"
#include "mbedtls/md5.h"
#include "esp_system.h"
// Brownout disable is board/SoC specific; guard to keep this portable across ESP32 variants.
#if defined(RTC_CNTL_BROWN_OUT_REG)
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#endif
#include "saira_config.h"
#include "saira_net.h"
#include "saira_ota.h"
#include "saira_remote_config.h"
#include "saira_wifi.h"

// =============================================================================
// TIMING
// =============================================================================
static const bool SAIRA_PRINT_TIMINGS = true;
static const bool SAIRA_QUEUE_COMPACT_DEBUG = false;

static inline uint32_t sairaMsSince(uint32_t t0) {
  return (uint32_t)(millis() - t0);
}

static inline void sairaPrintMs(const char* stage, uint32_t ms) {
  if (!SAIRA_PRINT_TIMINGS) return;
  Serial.printf("TIME %-20s %lu ms\n", stage, (unsigned long)ms);
}

static inline void sairaQueueDbg(const char* fmt, ...) {
  if (!SAIRA_QUEUE_COMPACT_DEBUG) return;
  char msg[192];
  va_list args;
  va_start(args, fmt);
  vsnprintf(msg, sizeof(msg), fmt, args);
  va_end(args);
  Serial.print("QDBG: ");
  Serial.println(msg);
}

// =============================================================================
// 1. NETWORK
// =============================================================================
const char* ssid = SAIRA_WIFI_SSID;
const char* password = SAIRA_WIFI_PASSWORD;

// =============================================================================
// 2. CAMERA IP (ORIGEM)
// =============================================================================
// Ex: http://192.168.0.142:80/snap.jpg
static String ipCamUrl = SAIRA_IP_CAM_URL;
static String ipCamUser = SAIRA_IP_CAM_USER;
static String ipCamPass = SAIRA_IP_CAM_PASS;

// =============================================================================
// 3. SERVIDOR (DESTINO)
// =============================================================================
// Base: ex: http(s)://xxxx.serveousercontent.com
static const char* SERVER_BASE = SAIRA_SERVER_BASE;
static const char* UPLOAD_PATH = "/upload";
static const char* STATUS_PATH = "/status";

static uint32_t timerDelayMs = SAIRA_TIMER_DELAY_MS;
static const bool SAIRA_REMOTE_DEBUG = (SAIRA_REMOTE_DEBUG_ENABLED != 0);
static uint32_t nextRemoteDebugAt = 0;
static uint32_t gCaptureOk = 0;
static uint32_t gCaptureFail = 0;
static uint32_t gUploadOk = 0;
static uint32_t gUploadFail = 0;
static uint32_t gLastCaptureBytes = 0;
static uint32_t gLastQueueBytes = 0;
static uint32_t gCompactFailCount = 0;
static uint32_t gCompactSuccessCount = 0;

// ATENCAO: para https, por padrao vamos aceitar qualquer certificado.
// Se quiser validacao, troque por setCACert() com o CA correto.
static const bool TLS_INSECURE = (SAIRA_TLS_INSECURE != 0);

static String b64Encode(const String& in) {
  // mbedTLS base64 output length: 4 * ceil(n/3) + 1
  size_t outLen = 4 * ((in.length() + 2) / 3) + 1;
  unsigned char* out = (unsigned char*)malloc(outLen);
  if (!out) return String();

  size_t olen = 0;
  int rc = mbedtls_base64_encode(out, outLen, &olen,
                                 (const unsigned char*)in.c_str(), in.length());
  if (rc != 0) {
    free(out);
    return String();
  }
  out[olen] = 0;
  String s((const char*)out);
  free(out);
  return s;
}

static void addPreemptiveBasicAuth(HTTPClient& http) {
  // Some IP cameras only accept Basic if it's sent on the first request
  // (browsers often do this when the URL contains user:pass@...).
  String token = b64Encode(ipCamUser + ":" + ipCamPass);
  if (token.length()) {
    http.addHeader("Authorization", "Basic " + token);
  }
}

static String md5Hex(const String& s) {
  unsigned char md[16];
  mbedtls_md5_context ctx;
  mbedtls_md5_init(&ctx);
  mbedtls_md5_starts_ret(&ctx);
  mbedtls_md5_update_ret(&ctx, (const unsigned char*)s.c_str(), s.length());
  mbedtls_md5_finish_ret(&ctx, md);
  mbedtls_md5_free(&ctx);

  static const char* hex = "0123456789abcdef";
  char out[33];
  for (int i = 0; i < 16; i++) {
    out[i * 2] = hex[(md[i] >> 4) & 0xF];
    out[i * 2 + 1] = hex[md[i] & 0xF];
  }
  out[32] = 0;
  return String(out);
}

struct DigestChallenge {
  bool ok = false;
  String realm;
  String nonce;
  String qop;
  String opaque;
  String algorithm; // e.g. "MD5"
};

static String _trimQuotes(const String& v) {
  if (v.length() >= 2 && ((v[0] == '"' && v[v.length() - 1] == '"') ||
                          (v[0] == '\'' && v[v.length() - 1] == '\''))) {
    return v.substring(1, v.length() - 1);
  }
  return v;
}

static DigestChallenge parseDigestChallenge(const String& header) {
  DigestChallenge c;
  String h = header;
  h.trim();
  if (!h.startsWith("Digest")) return c;

  // Remove leading "Digest"
  int sp = h.indexOf(' ');
  if (sp < 0) return c;
  h = h.substring(sp + 1);

  int i = 0;
  while (i < (int)h.length()) {
    while (i < (int)h.length() && (h[i] == ' ' || h[i] == ',')) i++;
    if (i >= (int)h.length()) break;

    int eq = h.indexOf('=', i);
    if (eq < 0) break;
    String key = h.substring(i, eq);
    key.trim();
    i = eq + 1;

    String val;
    if (i < (int)h.length() && h[i] == '"') {
      i++; // skip "
      int endq = h.indexOf('"', i);
      if (endq < 0) break;
      val = h.substring(i, endq);
      i = endq + 1;
    } else {
      int comma = h.indexOf(',', i);
      if (comma < 0) comma = h.length();
      val = h.substring(i, comma);
      val.trim();
      i = comma;
    }

    key.toLowerCase();
    if (key == "realm") c.realm = val;
    else if (key == "nonce") c.nonce = val;
    else if (key == "qop") c.qop = val;
    else if (key == "opaque") c.opaque = val;
    else if (key == "algorithm") c.algorithm = _trimQuotes(val);
  }

  if (c.realm.length() && c.nonce.length()) c.ok = true;
  return c;
}

static String randomHex8() {
  uint32_t r = esp_random();
  char buf[9];
  snprintf(buf, sizeof(buf), "%08x", (unsigned int)r);
  return String(buf);
}

static String buildDigestAuth(const DigestChallenge& c,
                              const String& method,
                              const String& uri,
                              const String& user,
                              const String& pass) {
  // Minimal RFC 7616 MD5 implementation. Works for most cameras that advertise Digest.
  // Supports qop=auth (most common) or missing qop.
  if (!c.ok) return String();
  if (c.algorithm.length() && c.algorithm != "MD5") {
    // Not implemented (e.g. SHA-256)
    return String();
  }

  String ha1 = md5Hex(user + ":" + c.realm + ":" + pass);
  String ha2 = md5Hex(method + ":" + uri);

  String nc = "00000001";
  String cnonce = randomHex8();

  String qop = c.qop;
  // qop can be "auth,auth-int" etc; pick auth if present.
  if (qop.indexOf("auth") >= 0) qop = "auth";
  else qop = "";

  String response;
  if (qop.length()) {
    response = md5Hex(ha1 + ":" + c.nonce + ":" + nc + ":" + cnonce + ":" + qop + ":" + ha2);
  } else {
    response = md5Hex(ha1 + ":" + c.nonce + ":" + ha2);
  }

  String auth = "Digest ";
  auth += "username=\"" + user + "\", ";
  auth += "realm=\"" + c.realm + "\", ";
  auth += "nonce=\"" + c.nonce + "\", ";
  auth += "uri=\"" + uri + "\", ";
  auth += "response=\"" + response + "\"";

  if (c.opaque.length()) auth += ", opaque=\"" + c.opaque + "\"";
  if (qop.length()) {
    auth += ", qop=" + qop;
    auth += ", nc=" + nc;
    auth += ", cnonce=\"" + cnonce + "\"";
  }

  auth += ", algorithm=MD5";
  return auth;
}

struct ParsedUrl {
  bool ok = false;
  bool https = false;
  String host;
  uint16_t port = 0;
  String path; // sempre comecando com '/'
};

static ParsedUrl parseHttpUrl(const String& url) {
  ParsedUrl out;
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
    String portStr = hostPort.substring(colon + 1);
    long p = portStr.toInt();
    if (p <= 0 || p > 65535) return ParsedUrl{};
    out.port = (uint16_t)p;
  } else {
    out.host = hostPort;
    out.port = out.https ? 443 : 80;
  }

  if (out.host.length() == 0) return ParsedUrl{};
  out.ok = true;
  return out;
}

static String joinPath(const String& base, const String& tail) {
  if (base.endsWith("/") && tail.startsWith("/")) return base + tail.substring(1);
  if (!base.endsWith("/") && !tail.startsWith("/")) return base + "/" + tail;
  return base + tail;
}

static void sendStatus(const String& msg);

#if SAIRA_USE_ETHERNET
static bool gEthStarted = false;
static bool gEthLinkReported = false;
static bool gEthBeginAttempted = false;
static bool gEthInitUnavailable = false;
static uint32_t gNextEthRetryAt = 0;
static uint32_t gNextWifiRetryAt = 0;

static bool connectWiFiUplink(uint32_t timeoutMs) {
  if (!(ssid && ssid[0])) return false;
  if (WiFi.status() == WL_CONNECTED) return true;
  Serial.println("NET: conectando Wi-Fi uplink...");
  bool ok = sairaConnectWiFi(ssid, password, SAIRA_DEVICE_ID, timeoutMs);
  if (ok) {
    Serial.print("NET: Wi-Fi conectado. IP=");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("NET: Wi-Fi uplink falhou.");
  }
  return ok;
}

static bool startEthernet(uint32_t timeoutMs) {
  if (!gEthStarted) {
    if (gEthInitUnavailable) return false;
    if (gEthBeginAttempted) return false;
    gEthBeginAttempted = true;

    Serial.println("NET: iniciando Ethernet...");
    ETH.setHostname(SAIRA_DEVICE_ID);

    if (!ETH.begin((uint8_t)SAIRA_ETH_ADDR,
                   (int)SAIRA_ETH_POWER_PIN,
                   (int)SAIRA_ETH_MDC_PIN,
                   (int)SAIRA_ETH_MDIO_PIN,
                   (eth_phy_type_t)SAIRA_ETH_TYPE,
                   (eth_clock_mode_t)SAIRA_ETH_CLK_MODE)) {
      Serial.println("NET: ETH.begin falhou.");
      Serial.println("NET: ETH sera mantida desativada neste boot para preservar Wi-Fi/OTA.");
      gEthInitUnavailable = true;
      return false;
    }
    gEthStarted = true;
  }

  uint32_t t0 = millis();
  while (!ETH.linkUp() && millis() - t0 < timeoutMs) {
    delay(200);
  }
  if (!ETH.linkUp()) {
    gEthLinkReported = false;
    Serial.println("NET: Ethernet sem link (timeout).");
    return false;
  }

  uint32_t tIp0 = millis();
  while (ETH.localIP() == INADDR_NONE && millis() - tIp0 < timeoutMs) {
    delay(200);
  }

  if (!gEthLinkReported) {
    gEthLinkReported = true;
    Serial.print("NET: Ethernet link UP. IP=");
    Serial.println(ETH.localIP());
    Serial.print("NET: gateway=");
    Serial.println(ETH.gatewayIP());
    Serial.print("NET: DNS=");
    Serial.println(ETH.dnsIP());
    Serial.print("NET: speed=");
    Serial.print((int)ETH.linkSpeed());
    Serial.print("Mbps duplex=");
    Serial.println(ETH.fullDuplex() ? "full" : "half");
  }
  return true;
}
#endif

static bool ensureNet() {
#if SAIRA_USE_ETHERNET
#if SAIRA_ETH_WIFI_DUAL_MODE
  // Dual mode: keep Ethernet for camera LAN and Wi-Fi for internet/OTA.
  bool ethOk = false;
  bool wifiOk = false;
  uint32_t now = millis();

  if (gNextEthRetryAt == 0 || (int32_t)(now - gNextEthRetryAt) >= 0) {
    gNextEthRetryAt = now + (uint32_t)SAIRA_ETH_RETRY_INTERVAL_MS;
    ethOk = startEthernet(3000);
  } else {
    ethOk = ETH.linkUp();
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiOk = true;
  } else if (gNextWifiRetryAt == 0 || (int32_t)(now - gNextWifiRetryAt) >= 0) {
    gNextWifiRetryAt = now + (uint32_t)SAIRA_WIFI_RETRY_INTERVAL_MS;
    wifiOk = connectWiFiUplink(6000);
  }

  return ethOk || wifiOk;
#else
  if (sairaNetConnected()) return true;
  uint32_t now = millis();

  if (gNextEthRetryAt == 0 || (int32_t)(now - gNextEthRetryAt) >= 0) {
    gNextEthRetryAt = now + (uint32_t)SAIRA_ETH_RETRY_INTERVAL_MS;
    if (startEthernet(3000)) return true;
  }

#if SAIRA_ETH_WIFI_FALLBACK
  if (WiFi.status() != WL_CONNECTED &&
      (gNextWifiRetryAt == 0 || (int32_t)(now - gNextWifiRetryAt) >= 0)) {
    gNextWifiRetryAt = now + (uint32_t)SAIRA_WIFI_RETRY_INTERVAL_MS;
    if (connectWiFiUplink(6000)) return true;
  }
#endif

  return sairaNetConnected();
#endif
#else
  if (WiFi.status() == WL_CONNECTED) return true;
  uint32_t t0 = millis();
  WiFi.reconnect();
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) {
    delay(200);
  }
  sairaPrintMs("wifi_reconnect", sairaMsSince(t0));
  return WiFi.status() == WL_CONNECTED;
#endif
}

#if SAIRA_USE_ETHERNET
static bool ensureUplinkNet() {
#if SAIRA_ETH_WIFI_DUAL_MODE
  if (WiFi.status() == WL_CONNECTED) return true;
  uint32_t now = millis();
  if (gNextWifiRetryAt == 0 || (int32_t)(now - gNextWifiRetryAt) >= 0) {
    gNextWifiRetryAt = now + (uint32_t)SAIRA_WIFI_RETRY_INTERVAL_MS;
    return connectWiFiUplink(6000);
  }
  return false;
#else
  return ensureNet();
#endif
}

static bool ensureCameraNet() {
#if SAIRA_ETH_WIFI_DUAL_MODE
  if (ETH.linkUp()) return true;
  uint32_t now = millis();
  if (gNextEthRetryAt == 0 || (int32_t)(now - gNextEthRetryAt) >= 0) {
    gNextEthRetryAt = now + (uint32_t)SAIRA_ETH_RETRY_INTERVAL_MS;
    return startEthernet(3000);
  }
  return false;
#else
  return ensureNet();
#endif
}
#else
static bool ensureUplinkNet() { return ensureNet(); }
static bool ensureCameraNet() { return ensureNet(); }
#endif

static bool connectBootNetwork(uint32_t timeoutMs) {
#if SAIRA_USE_ETHERNET
#if SAIRA_ETH_WIFI_DUAL_MODE
  uint32_t half = timeoutMs / 2;
  if (half < 3000) half = 3000;
  bool ethOk = startEthernet(half);
  bool wifiOk = connectWiFiUplink(timeoutMs);
  if (!ethOk) {
    Serial.println("NET: Ethernet indisponivel no boot (camera pode ficar offline ate o link subir).");
  }
  if (!wifiOk) {
    Serial.println("NET: Wi-Fi indisponivel no boot (OTA/upload aguardando reconnect).");
  }
  return ethOk || wifiOk;
#else
  uint32_t ethTimeout = timeoutMs;
#if SAIRA_ETH_WIFI_FALLBACK
  ethTimeout = timeoutMs / 2;
  if (ethTimeout < 3000) ethTimeout = 3000;
#endif
  if (startEthernet(ethTimeout)) return true;

#if SAIRA_ETH_WIFI_FALLBACK
  Serial.println("NET: Ethernet indisponivel no boot; ativando fallback Wi-Fi para manter OTA.");
  return tryWiFiFallback(timeoutMs);
#else
  return false;
#endif
#endif
#else
  return sairaConnectWiFi(ssid, password, SAIRA_DEVICE_ID, timeoutMs);
#endif
}

static void maybeSendRemoteDebug() {
  if (!SAIRA_REMOTE_DEBUG) return;
  const uint32_t now = millis();
  if (nextRemoteDebugAt != 0 && (int32_t)(now - nextRemoteDebugAt) < 0) return;
  nextRemoteDebugAt = now + (uint32_t)SAIRA_REMOTE_DEBUG_INTERVAL_MS;

  String msg = "DBG net=" + String(sairaNetKind()) +
               " ip=" + sairaNetLocalIP().toString() +
               " wifi=" + String((WiFi.status() == WL_CONNECTED) ? 1 : 0) +
#if SAIRA_USE_ETHERNET
               " eth=" + String(ETH.linkUp() ? 1 : 0) +
#endif
               " cap_ok=" + String(gCaptureOk) +
               " cap_fail=" + String(gCaptureFail) +
               " up_ok=" + String(gUploadOk) +
               " up_fail=" + String(gUploadFail) +
               " comp_ok=" + String(gCompactSuccessCount) +
               " comp_fail=" + String(gCompactFailCount) +
               " cap_b=" + String(gLastCaptureBytes) +
               " q_b=" + String(gLastQueueBytes) +
               " heap=" + String(ESP.getFreeHeap()) +
               " psram=" + String(ESP.getFreePsram());
  sendStatus(msg);
}

static void sendStatus(const String& msg) {
  uint32_t t0 = millis();
  if (!ensureUplinkNet()) return;
  uint32_t tWifi = sairaMsSince(t0);

  String base = String(SERVER_BASE);
  ParsedUrl u = parseHttpUrl(base);
  if (!u.ok) {
    Serial.println("Status: SERVER_BASE invalido (precisa http:// ou https://).");
    return;
  }

  String url = base;
  url = joinPath(url, STATUS_PATH);

  WiFiClient* plain = nullptr;
  WiFiClientSecure* tls = nullptr;
  HTTPClient http;

  uint32_t tBegin0 = millis();
  if (u.https) {
    tls = new WiFiClientSecure();
    if (TLS_INSECURE) tls->setInsecure();
    if (!http.begin(*tls, url)) {
      Serial.println("Status: http.begin() falhou.");
      delete tls;
      return;
    }
  } else {
    plain = new WiFiClient();
    if (!http.begin(*plain, url)) {
      Serial.println("Status: http.begin() falhou.");
      delete plain;
      return;
    }
  }
  uint32_t tBegin = sairaMsSince(tBegin0);

  http.setTimeout(8000);
  http.addHeader("Content-Type", "application/x-www-form-urlencoded");
  String body = "message=" + msg;

  uint32_t tPost0 = millis();
  int code = http.POST(body);
  uint32_t tPost = sairaMsSince(tPost0);
  Serial.print("Status ");
  Serial.print(url);
  Serial.print(" -> ");
  Serial.println(code);

  http.end();
  delete plain;
  delete tls;

  sairaPrintMs("status_wifi", tWifi);
  sairaPrintMs("status_begin", tBegin);
  sairaPrintMs("status_post", tPost);
  sairaPrintMs("status_total", sairaMsSince(t0));
}

// =============================================================================
// Persistent connection + Digest nonce cache for IP camera
// =============================================================================
static WiFiClient camClient;          // persistent TCP connection to camera
static HTTPClient camHttp;            // reused across captures
static bool camConnected = false;     // tracks if camHttp is active

// Digest nonce cache (avoids 3-request dance every capture)
static DigestChallenge cachedDigest;  // last known challenge
static uint32_t digestNc = 0;        // nonce count (incremented per request)
static String lastCamUrl;             // detect URL change -> invalidate cache

static String buildDigestAuthWithNc(const DigestChallenge& c,
                                    const String& method,
                                    const String& uri,
                                    const String& user,
                                    const String& pass,
                                    uint32_t nc) {
  if (!c.ok) return String();
  if (c.algorithm.length() && c.algorithm != "MD5") return String();

  String ha1 = md5Hex(user + ":" + c.realm + ":" + pass);
  String ha2 = md5Hex(method + ":" + uri);

  char ncStr[9];
  snprintf(ncStr, sizeof(ncStr), "%08x", (unsigned int)nc);
  String cnonce = randomHex8();

  String qop = c.qop;
  if (qop.indexOf("auth") >= 0) qop = "auth";
  else qop = "";

  String response;
  if (qop.length()) {
    response = md5Hex(ha1 + ":" + c.nonce + ":" + String(ncStr) + ":" + cnonce + ":" + qop + ":" + ha2);
  } else {
    response = md5Hex(ha1 + ":" + c.nonce + ":" + ha2);
  }

  String auth = "Digest ";
  auth += "username=\"" + user + "\", ";
  auth += "realm=\"" + c.realm + "\", ";
  auth += "nonce=\"" + c.nonce + "\", ";
  auth += "uri=\"" + uri + "\", ";
  auth += "response=\"" + response + "\"";

  if (c.opaque.length()) auth += ", opaque=\"" + c.opaque + "\"";
  if (qop.length()) {
    auth += ", qop=" + qop;
    auth += ", nc=" + String(ncStr);
    auth += ", cnonce=\"" + cnonce + "\"";
  }

  auth += ", algorithm=MD5";
  return auth;
}

static void camDisconnect() {
  if (camConnected) {
    camHttp.end();
    camConnected = false;
  }
  camClient.stop();
}

static bool downloadSnapshot(uint8_t*& outBuf, int& outLen) {
  outBuf = nullptr;
  outLen = 0;

  uint32_t t0 = millis();
  ParsedUrl cam = parseHttpUrl(ipCamUrl);
  if (!cam.ok) {
    Serial.println("IP_CAM_URL invalido (precisa http://...).");
    return false;
  }
  uint32_t tParse = sairaMsSince(t0);

  // Invalidate digest cache if URL changed
  if (ipCamUrl != lastCamUrl) {
    cachedDigest = DigestChallenge{};
    digestNc = 0;
    camDisconnect();
    lastCamUrl = ipCamUrl;
  }

  int code = -1;
  uint32_t tHttpTotal = 0;
  uint32_t tChallenge = 0;
  uint32_t tAlloc = 0;
  uint32_t tRead = 0;

  // Strategy: if we have a cached Digest nonce, try it first (1 request).
  // Otherwise, try Basic first, then fall back to Digest challenge.

  if (cachedDigest.ok) {
    // Fast path: reuse cached nonce (1 request instead of 3)
    digestNc++;
    String auth = buildDigestAuthWithNc(cachedDigest, "GET", cam.path,
                                         ipCamUser, ipCamPass, digestNc);
    if (auth.length()) {
      camDisconnect();
      if (camHttp.begin(camClient, ipCamUrl)) {
        camConnected = true;
        camHttp.setTimeout(8000);
        camHttp.addHeader("Connection", "keep-alive");
        camHttp.addHeader("Authorization", auth);
        uint32_t tReq0 = millis();
        code = camHttp.GET();
        tHttpTotal += sairaMsSince(tReq0);
      }
    }

    // Nonce expired? Server returns 401 -> re-challenge below
    if (code == 401) {
      Serial.println("Digest nonce expirado, re-autenticando...");
      cachedDigest = DigestChallenge{};
      digestNc = 0;
      camDisconnect();
      code = -1; // fall through to full auth
    }
  }

  if (code != 200 && !cachedDigest.ok) {
    // Try 1: Basic (preemptive) with keep-alive
    camDisconnect();
    if (camHttp.begin(camClient, ipCamUrl)) {
      camConnected = true;
      camHttp.setTimeout(8000);
      camHttp.addHeader("Connection", "keep-alive");
      addPreemptiveBasicAuth(camHttp);
      uint32_t tReq0 = millis();
      code = camHttp.GET();
      tHttpTotal += sairaMsSince(tReq0);
    }

    // Try 2: Digest fallback
    if (code == 401) {
      // Collect WWW-Authenticate header from current response
      static const char* collectKeys[] = {"WWW-Authenticate"};

      camDisconnect();
      WiFiClient chalClient;
      HTTPClient chalHttp;
      String wwwAuth;
      if (chalHttp.begin(chalClient, ipCamUrl)) {
        chalHttp.collectHeaders(collectKeys, 1);
        chalHttp.setTimeout(8000);
        uint32_t tCh0 = millis();
        int ccode = chalHttp.GET();
        tChallenge = sairaMsSince(tCh0);
        tHttpTotal += tChallenge;
        if (ccode > 0) {
          wwwAuth = chalHttp.header("WWW-Authenticate");
        }
        chalHttp.end();
      }

      DigestChallenge c = parseDigestChallenge(wwwAuth);
      if (c.ok) {
        // Cache it for future requests
        cachedDigest = c;
        digestNc = 1;

        String auth = buildDigestAuthWithNc(c, "GET", cam.path,
                                             ipCamUser, ipCamPass, digestNc);
        if (auth.length()) {
          if (camHttp.begin(camClient, ipCamUrl)) {
            camConnected = true;
            camHttp.setTimeout(8000);
            camHttp.addHeader("Connection", "keep-alive");
            camHttp.addHeader("Authorization", auth);
            uint32_t tReq0 = millis();
            code = camHttp.GET();
            tHttpTotal += sairaMsSince(tReq0);
          }
        }
      }
    }
  }

  if (code != 200) {
    Serial.print("Camera IP GET falhou: ");
    Serial.println(code);
    camDisconnect();
    sairaPrintMs("cam_parse", tParse);
    sairaPrintMs("cam_http_total", tHttpTotal);
    if (tChallenge) sairaPrintMs("cam_digest_chal", tChallenge);
    sairaPrintMs("cam_total", sairaMsSince(t0));
    return false;
  }

  int len = camHttp.getSize();
  if (len <= 0) {
    Serial.println("Camera IP retornou imagem vazia.");
    camDisconnect();
    sairaPrintMs("cam_parse", tParse);
    sairaPrintMs("cam_http_total", tHttpTotal);
    if (tChallenge) sairaPrintMs("cam_digest_chal", tChallenge);
    sairaPrintMs("cam_total", sairaMsSince(t0));
    return false;
  }

  uint32_t tAlloc0 = millis();
  uint8_t* buffer = (uint8_t*)ps_malloc((size_t)len);
  if (!buffer) {
    buffer = (uint8_t*)malloc((size_t)len);
    if (!buffer) {
      Serial.println("Sem memoria (psram/heap) para snapshot.");
      camDisconnect();
      tAlloc = sairaMsSince(tAlloc0);
      sairaPrintMs("cam_parse", tParse);
      sairaPrintMs("cam_http_total", tHttpTotal);
      if (tChallenge) sairaPrintMs("cam_digest_chal", tChallenge);
      sairaPrintMs("cam_alloc", tAlloc);
      sairaPrintMs("cam_total", sairaMsSince(t0));
      return false;
    }
  }
  tAlloc = sairaMsSince(tAlloc0);

  WiFiClient* stream = camHttp.getStreamPtr();
  if (stream) stream->setNoDelay(true);  // reduce TCP latency

  uint32_t tRead0 = millis();
  int total = 0;
  while (camHttp.connected() && total < len) {
    size_t avail = stream->available();
    if (!avail) {
      delay(1);
      continue;
    }
    size_t want = (size_t)(len - total);
    if (avail > want) avail = want;
    int readN = stream->readBytes(buffer + total, avail);
    if (readN <= 0) break;
    total += readN;
  }
  tRead = sairaMsSince(tRead0);

  // Don't call camHttp.end() — keep connection alive for next capture.
  // The server may close it (camera-dependent), which is handled on next call.

  if (total != len) {
    Serial.printf("Download incompleto: %d/%d bytes\n", total, len);
    free(buffer);
    camDisconnect();
    sairaPrintMs("cam_parse", tParse);
    sairaPrintMs("cam_http_total", tHttpTotal);
    if (tChallenge) sairaPrintMs("cam_digest_chal", tChallenge);
    sairaPrintMs("cam_alloc", tAlloc);
    sairaPrintMs("cam_read", tRead);
    sairaPrintMs("cam_total", sairaMsSince(t0));
    return false;
  }

  outBuf = buffer;
  outLen = total;

  sairaPrintMs("cam_parse", tParse);
  sairaPrintMs("cam_http_total", tHttpTotal);
  if (tChallenge) sairaPrintMs("cam_digest_chal", tChallenge);
  sairaPrintMs("cam_alloc", tAlloc);
  sairaPrintMs("cam_read", tRead);
  sairaPrintMs("cam_total", sairaMsSince(t0));
  return true;
}

static bool writeAll(Stream& s, const uint8_t* buf, size_t len) {
  size_t off = 0;
  while (off < len) {
    size_t chunk = len - off;
    if (chunk > 1024) chunk = 1024;
    size_t written = s.write(buf + off, chunk);
    if (written == 0) {
      return false;
    }
    off += written;
  }
  return true;
}

static void netProbe() {
  Serial.println("NET: probe...");

  // 1) Can we reach a well-known internet IP via TCP?
  {
    uint32_t t0 = millis();
    WiFiClient c;
    c.setTimeout(3000);
    bool ok = c.connect(IPAddress(8, 8, 8, 8), 53); // DNS over TCP
    Serial.print("NET: tcp 8.8.8.8:53 -> ");
    Serial.println(ok ? "OK" : "FAIL");
    c.stop();
    sairaPrintMs("net_8.8.8.8", sairaMsSince(t0));
  }

  // 2) Can we reach the EC2 directly (TCP)?
  {
    ParsedUrl up = parseHttpUrl(joinPath(String(SERVER_BASE), STATUS_PATH));
    if (up.ok) {
      uint32_t t0 = millis();
      WiFiClient c;
      c.setTimeout(5000);
      bool ok = c.connect(up.host.c_str(), up.port);
      Serial.print("NET: tcp ");
      Serial.print(up.host);
      Serial.print(":");
      Serial.print(up.port);
      Serial.print(" -> ");
      Serial.println(ok ? "OK" : "FAIL");
      c.stop();
      sairaPrintMs("net_server_tcp", sairaMsSince(t0));
    } else {
      Serial.println("NET: SERVER_BASE invalido, pulando probe EC2.");
    }
  }
}

static bool uploadSnapshot(const uint8_t* buf, int len) {
  uint32_t t0 = millis();
  if (!ensureUplinkNet()) return false;
  uint32_t tWifi = sairaMsSince(t0);

  String base = String(SERVER_BASE);
  ParsedUrl u = parseHttpUrl(base);
  if (!u.ok) {
    Serial.println("Upload: SERVER_BASE invalido (precisa http:// ou https://).");
    return false;
  }

  // Permite base com path (prefixo), ex: https://host/prefix
  String fullUploadUrl = joinPath(base, UPLOAD_PATH);
  ParsedUrl up = parseHttpUrl(fullUploadUrl);
  if (!up.ok) {
    Serial.println("Upload: URL final invalida.");
    return false;
  }

  WiFiClient plain;
  WiFiClientSecure tls;
  Stream* sock = nullptr;

  uint32_t tConn0 = millis();
  if (up.https) {
    if (TLS_INSECURE) tls.setInsecure();
    if (!tls.connect(up.host.c_str(), up.port)) {
      Serial.println("Upload: falha conectando TLS.");
      return false;
    }
    sock = &tls;
  } else {
    if (!plain.connect(up.host.c_str(), up.port)) {
      Serial.println("Upload: falha conectando.");
      return false;
    }
    sock = &plain;
  }
  uint32_t tConn = sairaMsSince(tConn0);

  const String boundary = "RandomBoundary";
  const String head =
    "--" + boundary + "\r\n"
    "Content-Disposition: form-data; name=\"imageFile\"; filename=\"snapshot_relay.jpg\"\r\n"
    "Content-Type: image/jpeg\r\n\r\n";
  const String tail = "\r\n--" + boundary + "--\r\n";

  uint32_t totalLen = (uint32_t)len + head.length() + tail.length();

  uint32_t tSend0 = millis();
  bool wroteOk = true;
  wroteOk &= (sock->print(String("POST ") + up.path + " HTTP/1.1\r\n") > 0);
  wroteOk &= (sock->print(String("Host: ") + up.host + "\r\n") > 0);
  wroteOk &= (sock->print("Connection: close\r\n") > 0);
  wroteOk &= (sock->print(String("Content-Type: multipart/form-data; boundary=") + boundary + "\r\n") > 0);
  wroteOk &= (sock->print(String("Content-Length: ") + String(totalLen) + "\r\n") > 0);
  wroteOk &= (sock->print(String("X-Device-Id: ") + String(SAIRA_DEVICE_ID) + "\r\n") > 0);
  wroteOk &= (sock->print("\r\n") > 0);
  wroteOk &= (sock->print(head) > 0);
  wroteOk &= writeAll(*sock, buf, (size_t)len);
  wroteOk &= (sock->print(tail) > 0);
  uint32_t tSend = sairaMsSince(tSend0);
  if (!wroteOk) {
    Serial.println("Upload: falha ao escrever payload (socket).");
    if (up.https) tls.stop();
    else plain.stop();
    sairaPrintMs("up_wifi", tWifi);
    sairaPrintMs("up_connect", tConn);
    sairaPrintMs("up_send", tSend);
    sairaPrintMs("up_total", sairaMsSince(t0));
    return false;
  }

  // Lê primeira linha da resposta (best-effort)
  uint32_t tWait0 = millis();
  while (millis() - tWait0 < 5000) {
    if (up.https ? tls.available() : plain.available()) break;
    delay(10);
  }
  uint32_t tWait = sairaMsSince(tWait0);

  String statusLine;
  if (up.https) statusLine = tls.readStringUntil('\n');
  else statusLine = plain.readStringUntil('\n');
  bool ok = statusLine.startsWith("HTTP/1.1 200") || statusLine.startsWith("HTTP/1.0 200");

  Serial.print("Upload ");
  Serial.print(fullUploadUrl);
  Serial.print(" -> ");
  Serial.println(statusLine.length() ? statusLine : "(sem resposta)");

  if (up.https) tls.stop();
  else plain.stop();

  sairaPrintMs("up_wifi", tWifi);
  sairaPrintMs("up_connect", tConn);
  sairaPrintMs("up_send", tSend);
  sairaPrintMs("up_wait", tWait);
  sairaPrintMs("up_total", sairaMsSince(t0));
  return ok;
}

static const uint8_t QUEUE_REENCODE_JPEG_QUALITY = 24;
static uint8_t* gQueueRgbWorkspace = nullptr;
static size_t gQueueRgbWorkspaceLen = 0;
static uint32_t gLastCompactWarnAt = 0;

static bool isSofMarker(uint8_t marker) {
    // SOF markers that carry width/height.
    switch (marker) {
        case 0xC0: case 0xC1: case 0xC2: case 0xC3:
        case 0xC5: case 0xC6: case 0xC7:
        case 0xC9: case 0xCA: case 0xCB:
        case 0xCD: case 0xCE: case 0xCF:
            return true;
        default:
            return false;
    }
}

static bool parseJpegDimensions(const uint8_t* data, size_t len, uint16_t& width, uint16_t& height) {
    width = 0;
    height = 0;
    if (!data || len < 4) {
        sairaQueueDbg("parse: buffer invalido (len=%u)", (unsigned int)len);
        return false;
    }
    if (data[0] != 0xFF || data[1] != 0xD8) {
        sairaQueueDbg("parse: nao eh JPEG SOI");
        return false; // SOI
    }

    size_t pos = 2;
    while (pos + 1 < len) {
        if (data[pos] != 0xFF) {
            pos++;
            continue;
        }
        while (pos < len && data[pos] == 0xFF) pos++;
        if (pos >= len) break;

        uint8_t marker = data[pos++];
        if (marker == 0x00) continue;
        if (marker == 0xD8 || marker == 0xD9) continue; // SOI/EOI
        if (marker >= 0xD0 && marker <= 0xD7) continue; // RSTn

        if (pos + 1 >= len) {
            sairaQueueDbg("parse: segmento truncado em pos=%u", (unsigned int)pos);
            return false;
        }
        uint16_t segLen = ((uint16_t)data[pos] << 8) | (uint16_t)data[pos + 1];
        if (segLen < 2) {
            sairaQueueDbg("parse: segLen invalido=%u marker=0x%02X", (unsigned int)segLen, (unsigned int)marker);
            return false;
        }
        if (pos + segLen > len) {
            sairaQueueDbg("parse: segLen fora do buffer marker=0x%02X segLen=%u pos=%u len=%u",
                          (unsigned int)marker, (unsigned int)segLen, (unsigned int)pos, (unsigned int)len);
            return false;
        }

        if (isSofMarker(marker)) {
            if (segLen < 7) return false;
            height = ((uint16_t)data[pos + 3] << 8) | (uint16_t)data[pos + 4];
            width = ((uint16_t)data[pos + 5] << 8) | (uint16_t)data[pos + 6];
            bool ok = (width > 0 && height > 0);
            if (ok) {
                sairaQueueDbg("parse: dimensoes %ux%u", (unsigned int)width, (unsigned int)height);
            } else {
                sairaQueueDbg("parse: SOF sem dimensoes validas");
            }
            return ok;
        }

        pos += segLen;
    }

    sairaQueueDbg("parse: SOF nao encontrado");
    return false;
}

static bool jpegMarkerHasLength(uint8_t marker) {
    if (marker == 0xD8 || marker == 0xD9) return false; // SOI / EOI
    if (marker >= 0xD0 && marker <= 0xD7) return false; // RST0..RST7
    if (marker == 0x01) return false;                   // TEM
    return true;
}

static bool shouldStripJpegSegment(uint8_t marker) {
    // Keep APP0 (JFIF) and APP14 (Adobe), strip the rest of APPn + COM metadata.
    if (marker == 0xE0 || marker == 0xEE) return false;
    if (marker == 0xFE) return true;                    // COM
    if (marker >= 0xE1 && marker <= 0xEF) return true; // APP1..APP15
    return false;
}

static bool compactJpegMetadataForQueue(uint8_t*& data, int& len) {
    if (!data || len <= 4) return false;
    const size_t srcLen = (size_t)len;
    const uint8_t* src = data;

    // JPEG starts with SOI: FF D8.
    if (src[0] != 0xFF || src[1] != 0xD8) return false;

    uint8_t* out = (uint8_t*)ps_malloc(srcLen);
    if (!out) out = (uint8_t*)malloc(srcLen);
    if (!out) return false;

    size_t inPos = 2;
    size_t outPos = 0;
    bool sawSos = false;

    out[outPos++] = 0xFF;
    out[outPos++] = 0xD8;

    while (inPos + 1 < srcLen) {
        if (src[inPos] != 0xFF) {
            free(out);
            return false;
        }

        while (inPos < srcLen && src[inPos] == 0xFF) inPos++;
        if (inPos >= srcLen) break;

        uint8_t marker = src[inPos++];
        if (marker == 0x00) {
            free(out);
            return false;
        }

        if (!jpegMarkerHasLength(marker)) {
            if (outPos + 2 > srcLen) {
                free(out);
                return false;
            }
            out[outPos++] = 0xFF;
            out[outPos++] = marker;
            if (marker == 0xD9) break;
            continue;
        }

        if (inPos + 1 >= srcLen) {
            free(out);
            return false;
        }

        const size_t segStart = inPos - 2; // includes 0xFF + marker
        const size_t segLen = ((size_t)src[inPos] << 8) | (size_t)src[inPos + 1];
        if (segLen < 2) {
            free(out);
            return false;
        }

        const size_t segTotal = segLen + 2;
        if (segStart + segTotal > srcLen) {
            free(out);
            return false;
        }

        const bool isSos = (marker == 0xDA);
        const bool strip = shouldStripJpegSegment(marker);

        if (!strip) {
            if (outPos + segTotal > srcLen) {
                free(out);
                return false;
            }
            memcpy(out + outPos, src + segStart, segTotal);
            outPos += segTotal;
        }

        inPos = segStart + segTotal;

        if (isSos) {
            const size_t rest = srcLen - inPos;
            if (outPos + rest > srcLen) {
                free(out);
                return false;
            }
            memcpy(out + outPos, src + inPos, rest);
            outPos += rest;
            sawSos = true;
            break;
        }
    }

    if (!sawSos || outPos >= srcLen) {
        free(out);
        return false;
    }

    uint8_t* shrunk = (uint8_t*)realloc(out, outPos);
    if (shrunk) out = shrunk;

    free(data);
    data = out;
    len = (int)outPos;
    return true;
}

static bool ensureQueueRgbWorkspace(size_t needed) {
    if (gQueueRgbWorkspace && gQueueRgbWorkspaceLen >= needed) return true;
    uint8_t* p = (uint8_t*)ps_malloc(needed);
    if (!p) p = (uint8_t*)malloc(needed);
    if (!p) return false;
    free(gQueueRgbWorkspace);
    gQueueRgbWorkspace = p;
    gQueueRgbWorkspaceLen = needed;
    return true;
}

static bool isLikelyValidJpeg(const uint8_t* data, int len) {
    if (!data || len < 4) return false;
    return (data[0] == 0xFF && data[1] == 0xD8 &&
            data[len - 2] == 0xFF && data[len - 1] == 0xD9);
}

static bool reencodeJpegForQueue(uint8_t*& data, int& len) {
    if (!data || len <= 4) return false;

    uint16_t width = 0, height = 0;
    if (!parseJpegDimensions(data, (size_t)len, width, height)) {
        sairaQueueDbg("reencode: parse de dimensoes falhou");
        return false;
    }

    const size_t rgbLen = (size_t)width * (size_t)height * 3;
    if (rgbLen == 0) {
        sairaQueueDbg("reencode: rgbLen=0");
        return false;
    }

    sairaQueueDbg("reencode: in=%d bytes, %ux%u, rgbLen=%u, heap=%u, psram=%u",
                  len, (unsigned int)width, (unsigned int)height, (unsigned int)rgbLen,
                  (unsigned int)ESP.getFreeHeap(), (unsigned int)ESP.getFreePsram());

    if (!ensureQueueRgbWorkspace(rgbLen)) {
        sairaQueueDbg("reencode: sem memoria para rgbLen=%u (heap=%u, psram=%u)",
                      (unsigned int)rgbLen, (unsigned int)ESP.getFreeHeap(), (unsigned int)ESP.getFreePsram());
        return false;
    }
    uint8_t* rgb = gQueueRgbWorkspace;

    if (!fmt2rgb888(data, (size_t)len, PIXFORMAT_JPEG, rgb)) {
        sairaQueueDbg("reencode: fmt2rgb888 falhou");
        return false;
    }

    uint8_t* out = nullptr;
    size_t outLen = 0;
    bool ok = fmt2jpg(rgb, rgbLen, width, height, PIXFORMAT_RGB888,
                      QUEUE_REENCODE_JPEG_QUALITY, &out, &outLen);

    if (!ok || !out || outLen == 0) {
        sairaQueueDbg("reencode: fmt2jpg falhou (ok=%d, out=%p, outLen=%u)",
                      ok ? 1 : 0, out, (unsigned int)outLen);
        free(out);
        return false;
    }

    if (outLen >= (size_t)len) {
        sairaQueueDbg("reencode: sem ganho (outLen=%u >= in=%d)", (unsigned int)outLen, len);
        free(out);
        return false;
    }

    free(data);
    data = out;
    len = (int)outLen;
    sairaQueueDbg("reencode: sucesso -> %d bytes", len);
    return true;
}

static bool compactJpegForQueue(uint8_t*& data, int& len, bool& wasReencoded) {
    wasReencoded = false;
    if (reencodeJpegForQueue(data, len)) {
        wasReencoded = true;
        return true;
    }
    // Avoid JPEG segment surgery on failure to prevent occasional corruption.
    return false;
}

// ---- Fila de imagens na PSRAM (thread-safe via mutex) ----
static const int IMAGE_QUEUE_MAX = 20;

struct QueuedImage {
    uint8_t* data;       // ponteiro PSRAM (ps_malloc)
    int      length;     // tamanho JPEG em bytes
    uint32_t capturedAt; // millis() da captura
};

static QueuedImage imageQueue[IMAGE_QUEUE_MAX];
static int queueHead = 0;  // proximo slot a ser consumido (upload)
static int queueTail = 0;  // proximo slot a ser escrito (captura)
static volatile int queueCount = 0;
static SemaphoreHandle_t queueMutex = NULL;

static bool queuePush(uint8_t* data, int len, uint32_t ts) {
    gLastCaptureBytes = (uint32_t)len;
    if (!isLikelyValidJpeg(data, len)) {
        Serial.printf("QUEUE: frame invalido (nao eh JPEG valido), descartado (%d bytes)\n", len);
        free(data);
        return false;
    }

    const int originalLen = len;
    bool wasReencoded = false;
    if (compactJpegForQueue(data, len, wasReencoded)) {
        gCompactSuccessCount++;
        const int saved = originalLen - len;
        const float pct = (originalLen > 0) ? (100.0f * (float)saved / (float)originalLen) : 0.0f;
        if (wasReencoded) {
            Serial.printf("QUEUE: recompressao JPEG q=%u %d -> %d bytes (-%d / %.1f%%)\n",
                          (unsigned int)QUEUE_REENCODE_JPEG_QUALITY, originalLen, len, saved, pct);
        } else {
            Serial.printf("QUEUE: compactou metadados JPEG %d -> %d bytes (-%d / %.1f%%)\n",
                          originalLen, len, saved, pct);
        }
    } else {
        gCompactFailCount++;
        Serial.printf("QUEUE: sem compactacao adicional (%d bytes)\n", len);
        uint32_t now = millis();
        if ((int32_t)(now - gLastCompactWarnAt) >= 300000) {
            gLastCompactWarnAt = now;
            sendStatus("WARN compactacao falhou; enviando original. ok=" + String(gCompactSuccessCount) +
                       " fail=" + String(gCompactFailCount) +
                       " heap=" + String(ESP.getFreeHeap()) +
                       " psram=" + String(ESP.getFreePsram()));
        }
    }
    gLastQueueBytes = (uint32_t)len;

    if (xSemaphoreTake(queueMutex, pdMS_TO_TICKS(1000)) != pdTRUE) {
        Serial.println("QUEUE: timeout obtendo mutex (push)");
        free(data);
        return false;
    }
    if (queueCount >= IMAGE_QUEUE_MAX) {
        free(imageQueue[queueHead].data);
        queueHead = (queueHead + 1) % IMAGE_QUEUE_MAX;
        queueCount--;
        Serial.println("QUEUE: descartou imagem mais antiga (fila cheia)");
    }
    imageQueue[queueTail].data = data;
    imageQueue[queueTail].length = len;
    imageQueue[queueTail].capturedAt = ts;
    queueTail = (queueTail + 1) % IMAGE_QUEUE_MAX;
    queueCount++;
    Serial.printf("QUEUE: enfileirou (%d bytes), total na fila: %d\n", len, queueCount);
    xSemaphoreGive(queueMutex);
    return true;
}

static bool queuePop(QueuedImage& out) {
    if (xSemaphoreTake(queueMutex, pdMS_TO_TICKS(1000)) != pdTRUE) {
        Serial.println("QUEUE: timeout obtendo mutex (pop)");
        return false;
    }
    if (queueCount <= 0) {
        xSemaphoreGive(queueMutex);
        return false;
    }
    out = imageQueue[queueHead];
    imageQueue[queueHead] = {nullptr, 0, 0};
    queueHead = (queueHead + 1) % IMAGE_QUEUE_MAX;
    queueCount--;
    xSemaphoreGive(queueMutex);
    return true;
}

// ---- Upload task (runs on core 0, parallel to capture on core 1) ----
static void uploadTask(void* /*param*/) {
    Serial.println("UPLOAD_TASK: iniciada no core 0");
    for (;;) {
        if (queueCount > 0 && ensureUplinkNet()) {
            QueuedImage img;
            if (queuePop(img)) {
                uint32_t now = millis();
                if (img.capturedAt) {
                    sairaPrintMs("queue_delay", (uint32_t)(now - img.capturedAt));
                }
                Serial.printf("\n--- UPLOAD (fila restante: %d) ---\n", queueCount);
                if (uploadSnapshot(img.data, img.length)) {
                    gUploadOk++;
                } else {
                    gUploadFail++;
                    sendStatus("ERR upload falhou net=" + String(sairaNetKind()) +
                               " q=" + String(queueCount) +
                               " heap=" + String(ESP.getFreeHeap()));
                }
                free(img.data);
            }
        }
        maybeSendRemoteDebug();
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void setup() {
  Serial.begin(115200);
#if defined(RTC_CNTL_BROWN_OUT_REG)
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
#endif

  Serial.print("Conectando rede");
  if (!connectBootNetwork(30000)) {
    Serial.println("NET: sem conectividade inicial; seguindo em modo degradado (OTA/rede continuam tentando).");
  }

  // Mutex para acesso thread-safe a fila de imagens
  queueMutex = xSemaphoreCreateMutex();

  // Upload roda no core 0 em paralelo com captura no core 1 (loop)
  xTaskCreatePinnedToCore(
      uploadTask,   // funcao
      "upload",     // nome
      8192,         // stack (bytes)
      NULL,         // param
      1,            // prioridade (mesma do loop)
      NULL,         // handle (nao precisamos)
      0             // core 0 (WiFi protocol task tambem roda aqui)
  );
  Serial.println("Upload task criada no core 0");

  netProbe();
  sendStatus("ESP32 online (ipcam-relay) net=" + String(sairaNetKind()) +
             " ip=" + sairaNetLocalIP().toString());
}

static uint32_t nextCaptureAt = 0;

void loop() {
  sairaMaybeCheckOta();

  // Remote config (manter logica existente)
  auto applyFn = +[](const String& key, const String& value) -> bool {
    bool changed = false;
    String k = key; k.toLowerCase();
    if (k == "timer_delay_ms") {
      long v = value.toInt();
      if (v >= 1000 && (uint32_t)v != timerDelayMs) {
        timerDelayMs = (uint32_t)v;
        changed = true;
      }
    } else if (k == "ip_cam_url") {
      if (value.length() && value != ipCamUrl) { ipCamUrl = value; changed = true; }
    } else if (k == "ip_cam_user") {
      if (value != ipCamUser) { ipCamUser = value; changed = true; }
    } else if (k == "ip_cam_pass") {
      if (value != ipCamPass) { ipCamPass = value; changed = true; }
    }
    if (changed) Serial.println("CFG: aplicado (ipcam-relay).");
    return changed;
  };
  (void)sairaMaybeFetchRemoteConfig(String(SERVER_BASE), applyFn);

  // 1. CAPTURA em intervalo fixo
  if (nextCaptureAt == 0) nextCaptureAt = millis();
  if ((int32_t)(millis() - nextCaptureAt) >= 0) {
    // IMPORTANTE: avancar timer ANTES do download para manter intervalo fixo
    nextCaptureAt += timerDelayMs;

    // Evitar acumulo se ficou muito tempo sem rodar
    if ((int32_t)(millis() - nextCaptureAt) >= (int32_t)timerDelayMs) {
      nextCaptureAt = millis() + timerDelayMs;
    }

    if (ensureCameraNet()) {
      uint8_t* buf = nullptr;
      int len = 0;
      Serial.println("\n--- CAPTURA ---");
      uint32_t tCap0 = millis();
      if (downloadSnapshot(buf, len)) {
        gCaptureOk++;
        sairaPrintMs("capture_total", sairaMsSince(tCap0));
        Serial.printf("   OK: %d bytes capturados\n", len);
        if (!queuePush(buf, len, millis())) {
          sendStatus("ERR fila descartou frame cap_b=" + String(gLastCaptureBytes) +
                     " q_b=" + String(gLastQueueBytes) +
                     " heap=" + String(ESP.getFreeHeap()) +
                     " psram=" + String(ESP.getFreePsram()));
        }
        // NAO fazer free(buf) aqui — a fila agora eh dona do ponteiro
      } else {
        gCaptureFail++;
        sairaPrintMs("capture_total", sairaMsSince(tCap0));
        Serial.println("   ERRO: falha na captura");
        sendStatus("ERR captura falhou net=" + String(sairaNetKind()) +
                   " heap=" + String(ESP.getFreeHeap()) +
                   " psram=" + String(ESP.getFreePsram()));
      }
    }
  }

  maybeSendRemoteDebug();
  // Upload agora roda em paralelo no core 0 (uploadTask)
}
