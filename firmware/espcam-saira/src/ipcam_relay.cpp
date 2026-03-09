#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "esp_log.h"
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
#include "saira_ota.h"
#include "saira_remote_config.h"
#include "saira_runtime_config.h"
#include "saira_wifi.h"

// =============================================================================
// TIMING
// =============================================================================
static const bool SAIRA_PRINT_TIMINGS = true;

static inline uint32_t sairaMsSince(uint32_t t0) {
  return (uint32_t)(millis() - t0);
}

static inline void sairaPrintMs(const char* stage, uint32_t ms) {
  if (!SAIRA_PRINT_TIMINGS) return;
  Serial.printf("TIME %-20s %lu ms\n", stage, (unsigned long)ms);
}

// =============================================================================
// 1. WI-FI
// =============================================================================
static String gDeviceId;
static String gWifiSsid;
static String gWifiPassword;

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

static bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  uint32_t t0 = millis();
  WiFi.reconnect();
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) {
    delay(200);
  }
  sairaPrintMs("wifi_reconnect", sairaMsSince(t0));
  return WiFi.status() == WL_CONNECTED;
}

static void sendStatus(const String& msg) {
  uint32_t t0 = millis();
  if (!ensureWiFi()) return;
  uint32_t tWifi = sairaMsSince(t0);

  String base = String(SERVER_BASE);
  ParsedUrl u = parseHttpUrl(base);
  if (!u.ok) {
    Serial.println("Status: SERVER_BASE invalido (precisa http:// ou https://).");
    return;
  }

  String url = base;
  url = joinPath(url, STATUS_PATH);

  WiFiClient plain;
  WiFiClientSecure tls;
  HTTPClient http;

  uint32_t tBegin0 = millis();
  if (u.https) {
    if (TLS_INSECURE) tls.setInsecure();
    if (!http.begin(tls, url)) {
      Serial.println("Status: http.begin() falhou.");
      return;
    }
  } else {
    if (!http.begin(plain, url)) {
      Serial.println("Status: http.begin() falhou.");
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

  // Don't call camHttp.end() - keep connection alive for next capture.
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

static bool writeAllWithTimeout(Client& c, const uint8_t* buf, size_t len,
                                uint32_t timeoutMs, const char* stage) {
  size_t off = 0;
  uint32_t lastProgress = millis();
  while (off < len) {
    size_t chunk = len - off;
    if (chunk > 1024) chunk = 1024;
    size_t written = c.write(buf + off, chunk);
    if (written > 0) {
      off += written;
      lastProgress = millis();
      continue;
    }
    if ((uint32_t)(millis() - lastProgress) >= timeoutMs) {
      Serial.printf("Upload: timeout escrevendo %s (%u/%u bytes)\n",
                    stage,
                    (unsigned int)off,
                    (unsigned int)len);
      return false;
    }
    delay(2);
  }
  return true;
}

static bool writeTextWithTimeout(Client& c, const String& text,
                                 uint32_t timeoutMs, const char* stage) {
  return writeAllWithTimeout(c,
                             (const uint8_t*)text.c_str(),
                             (size_t)text.length(),
                             timeoutMs,
                             stage);
}

static int parseHttpStatusCode(const String& statusLine) {
  int firstSpace = statusLine.indexOf(' ');
  if (firstSpace < 0) return -1;
  int secondSpace = statusLine.indexOf(' ', firstSpace + 1);
  String codeStr = (secondSpace < 0)
                     ? statusLine.substring(firstSpace + 1)
                     : statusLine.substring(firstSpace + 1, secondSpace);
  codeStr.trim();
  long code = codeStr.toInt();
  if (code <= 0) return -1;
  return (int)code;
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
  if (!ensureWiFi()) {
    Serial.println("Upload: WiFi indisponivel antes do envio.");
    return false;
  }
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
  Client* sock = nullptr;
  constexpr uint8_t kMaxConnectAttempts = 3;
  constexpr uint32_t kWriteTimeoutMs = 15000;
  constexpr uint32_t kFirstResponseTimeoutMs = 5000;

  uint32_t tConn0 = millis();
  if (up.https) {
    if (TLS_INSECURE) tls.setInsecure();
    tls.setTimeout(5000);
    bool connected = false;
    for (uint8_t attempt = 1; attempt <= kMaxConnectAttempts; ++attempt) {
      if (tls.connect(up.host.c_str(), up.port)) {
        connected = true;
        break;
      }
      Serial.printf("Upload: falha conectando TLS (%s:%u), tentativa %u/%u\n",
                    up.host.c_str(), (unsigned int)up.port,
                    (unsigned int)attempt, (unsigned int)kMaxConnectAttempts);
      if (attempt < kMaxConnectAttempts) {
        if (WiFi.status() != WL_CONNECTED) {
          (void)ensureWiFi();
        }
        delay(250);
      }
    }
    if (!connected) {
      Serial.printf("Upload: sem conexao TLS com %s:%u apos %u tentativas\n",
                    up.host.c_str(), (unsigned int)up.port,
                    (unsigned int)kMaxConnectAttempts);
      return false;
    }
    sock = &tls;
  } else {
    plain.setTimeout(5000);
    bool connected = false;
    for (uint8_t attempt = 1; attempt <= kMaxConnectAttempts; ++attempt) {
      if (plain.connect(up.host.c_str(), up.port)) {
        connected = true;
        break;
      }
      Serial.printf("Upload: falha conectando (%s:%u), tentativa %u/%u\n",
                    up.host.c_str(), (unsigned int)up.port,
                    (unsigned int)attempt, (unsigned int)kMaxConnectAttempts);
      if (attempt < kMaxConnectAttempts) {
        if (WiFi.status() != WL_CONNECTED) {
          (void)ensureWiFi();
        }
        delay(250);
      }
    }
    if (!connected) {
      Serial.printf("Upload: sem conexao com %s:%u apos %u tentativas\n",
                    up.host.c_str(), (unsigned int)up.port,
                    (unsigned int)kMaxConnectAttempts);
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

  String reqHead;
  reqHead.reserve(256);
  reqHead += "POST " + up.path + " HTTP/1.1\r\n";
  reqHead += "Host: " + up.host + "\r\n";
  reqHead += "Connection: close\r\n";
  reqHead += "Content-Type: multipart/form-data; boundary=" + boundary + "\r\n";
  reqHead += "Content-Length: " + String(totalLen) + "\r\n";
  reqHead += "X-Device-Id: " + gDeviceId + "\r\n\r\n";

  uint32_t tSend0 = millis();
  bool sendOk = true;
  sendOk = sendOk && writeTextWithTimeout(*sock, reqHead, kWriteTimeoutMs, "cabecalho");
  sendOk = sendOk && writeTextWithTimeout(*sock, head, kWriteTimeoutMs, "multipart head");
  sendOk = sendOk && writeAllWithTimeout(*sock, buf, (size_t)len, kWriteTimeoutMs, "jpeg");
  sendOk = sendOk && writeTextWithTimeout(*sock, tail, kWriteTimeoutMs, "multipart tail");
  uint32_t tSend = sairaMsSince(tSend0);

  if (!sendOk) {
    if (up.https) tls.stop();
    else plain.stop();
    sairaPrintMs("up_wifi", tWifi);
    sairaPrintMs("up_connect", tConn);
    sairaPrintMs("up_send", tSend);
    sairaPrintMs("up_total", sairaMsSince(t0));
    return false;
  }

  // Le primeira linha da resposta (best-effort)
  uint32_t tWait0 = millis();
  while (millis() - tWait0 < kFirstResponseTimeoutMs) {
    if (up.https ? tls.available() : plain.available()) break;
    delay(10);
  }
  uint32_t tWait = sairaMsSince(tWait0);

  String statusLine;
  if (up.https) statusLine = tls.readStringUntil('\n');
  else statusLine = plain.readStringUntil('\n');
  int statusCode = parseHttpStatusCode(statusLine);

  Serial.print("Upload ");
  Serial.print(fullUploadUrl);
  Serial.print(" -> ");
  Serial.println(statusLine.length() ? statusLine : "(sem resposta)");
  if (statusCode < 200 || statusCode >= 300) {
    Serial.printf("Upload: resposta HTTP invalida (code=%d)\n", statusCode);
  }

  if (up.https) tls.stop();
  else plain.stop();

  sairaPrintMs("up_wifi", tWifi);
  sairaPrintMs("up_connect", tConn);
  sairaPrintMs("up_send", tSend);
  sairaPrintMs("up_wait", tWait);
  sairaPrintMs("up_total", sairaMsSince(t0));
  return (statusCode >= 200 && statusCode < 300);
}
static const uint8_t QUEUE_REENCODE_JPEG_QUALITY = 12;
static uint8_t* gQueueRgbWorkspace = nullptr;
static size_t gQueueRgbWorkspaceLen = 0;

// Crop config por device (0,0,0,0 = sem crop)
static int gCropX = 0, gCropY = 0, gCropW = 0, gCropH = 0;

static bool isSofMarker(uint8_t marker) {
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
  if (!data || len < 4) return false;
  if (data[0] != 0xFF || data[1] != 0xD8) return false;

  size_t pos = 2;
  while (pos + 1 < len) {
    if (data[pos] != 0xFF) {
      pos++;
      continue;
    }
    while (pos < len && data[pos] == 0xFF) pos++;
    if (pos >= len) break;

    uint8_t marker = data[pos++];
    if (marker == 0x00 || marker == 0xD8 || marker == 0xD9) continue;
    if (marker >= 0xD0 && marker <= 0xD7) continue;

    if (pos + 1 >= len) return false;
    uint16_t segLen = ((uint16_t)data[pos] << 8) | (uint16_t)data[pos + 1];
    if (segLen < 2 || pos + segLen > len) return false;

    if (isSofMarker(marker)) {
      if (segLen < 7) return false;
      height = ((uint16_t)data[pos + 3] << 8) | (uint16_t)data[pos + 4];
      width = ((uint16_t)data[pos + 5] << 8) | (uint16_t)data[pos + 6];
      return (width > 0 && height > 0);
    }

    pos += segLen;
  }
  return false;
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

static bool compactJpegForQueue(uint8_t*& data, int& len) {
  if (!data || len <= 4) return false;

  uint16_t width = 0, height = 0;
  if (!parseJpegDimensions(data, (size_t)len, width, height)) return false;

  size_t rgbLen = (size_t)width * (size_t)height * 3;
  if (rgbLen == 0) return false;
  if (!ensureQueueRgbWorkspace(rgbLen)) return false;

  uint8_t* rgb = gQueueRgbWorkspace;
  if (!fmt2rgb888(data, (size_t)len, PIXFORMAT_JPEG, rgb)) return false;

  // Aplica crop se configurado (mesmo pass do decode, sem custo extra)
  uint16_t encW = width, encH = height;
  uint8_t* encRgb = rgb;
  uint8_t* cropBuf = nullptr;

  if (gCropW > 0 && gCropH > 0) {
    int cx = gCropX < 0 ? 0 : gCropX;
    int cy = gCropY < 0 ? 0 : gCropY;
    int cw = gCropW;
    int ch = gCropH;
    if (cx + cw > (int)width)  cw = (int)width  - cx;
    if (cy + ch > (int)height) ch = (int)height - cy;
    if (cw > 0 && ch > 0 && (cw < (int)width || ch < (int)height)) {
      size_t cropRgbLen = (size_t)cw * (size_t)ch * 3;
      cropBuf = (uint8_t*)ps_malloc(cropRgbLen);
      if (!cropBuf) cropBuf = (uint8_t*)malloc(cropRgbLen);
      if (cropBuf) {
        for (int row = 0; row < ch; row++) {
          memcpy(cropBuf + (size_t)row * cw * 3,
                 rgb + ((size_t)(cy + row) * width + cx) * 3,
                 (size_t)cw * 3);
        }
        encW   = (uint16_t)cw;
        encH   = (uint16_t)ch;
        encRgb = cropBuf;
        Serial.printf("CROP: %dx%d -> %dx%d (x=%d y=%d)\n",
                      (int)width, (int)height, cw, ch, cx, cy);
      }
    }
  }

  size_t encRgbLen = (size_t)encW * (size_t)encH * 3;
  uint8_t* out = nullptr;
  size_t outLen = 0;
  bool ok = fmt2jpg(encRgb, encRgbLen, encW, encH, PIXFORMAT_RGB888,
                    QUEUE_REENCODE_JPEG_QUALITY, &out, &outLen);
  free(cropBuf);

  if (!ok || !out || outLen == 0) {
    free(out);
    return false;
  }
  // Se houve crop: aceita sempre (imagem menor é o objetivo).
  // Sem crop: só aceita se realmente comprimiu.
  bool wasCropped = (encW < width || encH < height);
  if (!wasCropped && outLen >= (size_t)len) {
    free(out);
    return false;
  }

  free(data);
  data = out;
  len = (int)outLen;
  return true;
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
static volatile bool gUploadInProgress = false;
static bool gCaptureBackpressure = false;
static uint32_t gLastBackpressureLogMs = 0;
static const int CAPTURE_PAUSE_QUEUE_THRESHOLD = 8;
static const int CAPTURE_RESUME_QUEUE_THRESHOLD = 3;

static bool queuePush(uint8_t* data, int len, uint32_t ts) {
    if (!isLikelyValidJpeg(data, len)) {
        Serial.printf("QUEUE: frame invalido (nao eh JPEG valido), descartado (%d bytes)\n", len);
        free(data);
        return false;
    }

    const int originalLen = len;
    if (compactJpegForQueue(data, len)) {
        const int saved = originalLen - len;
        const float pct = (originalLen > 0) ? (100.0f * (float)saved / (float)originalLen) : 0.0f;
        Serial.printf("QUEUE: recompressao JPEG q=%u %d -> %d bytes (-%d / %.1f%%)\n",
                      (unsigned int)QUEUE_REENCODE_JPEG_QUALITY, originalLen, len, saved, pct);
    } else {
        Serial.printf("QUEUE: sem compactacao adicional (%d bytes)\n", len);
    }

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
        if (queueCount > 0 && WiFi.status() == WL_CONNECTED) {
            QueuedImage img;
            if (queuePop(img)) {
                uint32_t now = millis();
                if (img.capturedAt) {
                    sairaPrintMs("queue_delay", (uint32_t)(now - img.capturedAt));
                }
                Serial.printf("\n--- UPLOAD (fila restante: %d) ---\n", queueCount);
                gUploadInProgress = true;
                uint32_t upT0 = millis();
                bool upOk = uploadSnapshot(img.data, img.length);
                gUploadInProgress = false;
                uint32_t upMs = sairaMsSince(upT0);
                Serial.printf("UPLOAD: %s (%lu ms), fila atual: %d\n",
                              upOk ? "OK" : "ERRO",
                              (unsigned long)upMs,
                              queueCount);
                free(img.data);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void setup() {
  Serial.begin(115200);
  // We emit our own connection diagnostics; suppress raw WiFiClient socket spam.
  esp_log_level_set("WiFiClient", ESP_LOG_NONE);
#if defined(RTC_CNTL_BROWN_OUT_REG)
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
#endif

  SairaRuntimeConfig rt = sairaLoadRuntimeConfig();
  gDeviceId = rt.deviceId.length() ? rt.deviceId : String(SAIRA_DEVICE_ID);
  gWifiSsid = rt.wifiSsid;
  gWifiPassword = rt.wifiPassword;
  Serial.printf("CFG runtime: device_id=%s ssid=%s\n", gDeviceId.c_str(), gWifiSsid.c_str());

  Serial.print("Conectando WiFi");
  if (!sairaConnectWiFi(gWifiSsid.c_str(), gWifiPassword.c_str(), gDeviceId.c_str(), 30000)) {
    Serial.println("WiFi: reboot em 5s...");
    delay(5000);
    ESP.restart();
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
  sendStatus("ESP32 online (ipcam-relay)");
}

static uint32_t nextCaptureAt = 0;

void loop() {
  if (!gCaptureBackpressure && queueCount >= CAPTURE_PAUSE_QUEUE_THRESHOLD) {
    gCaptureBackpressure = true;
    gLastBackpressureLogMs = millis();
    Serial.printf("CAPTURE: pausa por backlog (fila=%d, limite=%d)\n",
                  queueCount, CAPTURE_PAUSE_QUEUE_THRESHOLD);
  } else if (gCaptureBackpressure && queueCount <= CAPTURE_RESUME_QUEUE_THRESHOLD) {
    gCaptureBackpressure = false;
    Serial.printf("CAPTURE: retomada (fila=%d)\n", queueCount);
  }
  if (gCaptureBackpressure) {
    if ((uint32_t)(millis() - gLastBackpressureLogMs) >= 5000) {
      gLastBackpressureLogMs = millis();
      Serial.printf("CAPTURE: aguardando fila reduzir (fila=%d)\n", queueCount);
    }
    delay(20);
    return;
  }

  // Evita concorrencia de conexoes com a task de upload (core 0).
  if (!gUploadInProgress && queueCount == 0) {
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
      } else if (k == "crop_x") {
        int v = (int)value.toInt();
        if (v != gCropX) { gCropX = v; changed = true; }
      } else if (k == "crop_y") {
        int v = (int)value.toInt();
        if (v != gCropY) { gCropY = v; changed = true; }
      } else if (k == "crop_w") {
        int v = (int)value.toInt();
        if (v != gCropW) { gCropW = v; changed = true; }
      } else if (k == "crop_h") {
        int v = (int)value.toInt();
        if (v != gCropH) { gCropH = v; changed = true; }
      }
      if (changed) Serial.printf("CFG: aplicado (ipcam-relay) crop=%dx%d+%d+%d.\n",
                                 gCropW, gCropH, gCropX, gCropY);
      return changed;
    };
    (void)sairaMaybeFetchRemoteConfig(String(SERVER_BASE), applyFn, gDeviceId);
  }

  // 1. CAPTURA em intervalo fixo
  if (nextCaptureAt == 0) nextCaptureAt = millis();
  if ((int32_t)(millis() - nextCaptureAt) >= 0) {
    // IMPORTANTE: avancar timer ANTES do download para manter intervalo fixo
    nextCaptureAt += timerDelayMs;

    // Evitar acumulo se ficou muito tempo sem rodar
    if ((int32_t)(millis() - nextCaptureAt) >= (int32_t)timerDelayMs) {
      nextCaptureAt = millis() + timerDelayMs;
    }

    if (ensureWiFi()) {
      uint8_t* buf = nullptr;
      int len = 0;
      Serial.println("\n--- CAPTURA ---");
      uint32_t tCap0 = millis();
      if (downloadSnapshot(buf, len)) {
        sairaPrintMs("capture_total", sairaMsSince(tCap0));
        Serial.printf("   OK: %d bytes capturados\n", len);
        queuePush(buf, len, millis());
        // NAO fazer free(buf) aqui - a fila agora eh dona do ponteiro
      } else {
        sairaPrintMs("capture_total", sairaMsSince(tCap0));
        Serial.println("   ERRO: falha na captura");
      }
    }
  }

  // Upload agora roda em paralelo no core 0 (uploadTask)
}
