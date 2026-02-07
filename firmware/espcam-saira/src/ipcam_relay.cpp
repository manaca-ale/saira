#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "mbedtls/base64.h"
#include "mbedtls/md5.h"
#include "esp_system.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "saira_config.h"

// =============================================================================
// 1. WI-FI
// =============================================================================
const char* ssid = SAIRA_WIFI_SSID;
const char* password = SAIRA_WIFI_PASSWORD;

// =============================================================================
// 2. CAMERA IP (ORIGEM)
// =============================================================================
// Ex: http://192.168.0.142:80/snap.jpg
static const char* IP_CAM_URL = SAIRA_IP_CAM_URL;
static const char* IP_CAM_USER = SAIRA_IP_CAM_USER;
static const char* IP_CAM_PASS = SAIRA_IP_CAM_PASS;

// =============================================================================
// 3. SERVIDOR (DESTINO)
// =============================================================================
// Base: ex: http(s)://xxxx.serveousercontent.com
static const char* SERVER_BASE = SAIRA_SERVER_BASE;
static const char* UPLOAD_PATH = "/upload";
static const char* STATUS_PATH = "/status";

static const uint32_t TIMER_DELAY_MS = SAIRA_TIMER_DELAY_MS;
static uint32_t nextRunAt = 0;

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
  String token = b64Encode(String(IP_CAM_USER) + ":" + IP_CAM_PASS);
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
  WiFi.reconnect();
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) {
    delay(200);
  }
  return WiFi.status() == WL_CONNECTED;
}

static void sendStatus(const String& msg) {
  if (!ensureWiFi()) return;

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

  http.setTimeout(8000);
  http.addHeader("Content-Type", "application/x-www-form-urlencoded");
  String body = "message=" + msg;

  int code = http.POST(body);
  Serial.print("Status ");
  Serial.print(url);
  Serial.print(" -> ");
  Serial.println(code);

  http.end();
  delete plain;
  delete tls;
}

static bool downloadSnapshot(uint8_t*& outBuf, int& outLen) {
  outBuf = nullptr;
  outLen = 0;

  ParsedUrl cam = parseHttpUrl(String(IP_CAM_URL));
  if (!cam.ok) {
    Serial.println("IP_CAM_URL invalido (precisa http://...).");
    return false;
  }

  int code = -1;
  HTTPClient http;

  // Try 1: Basic (preemptive)
  http.begin(IP_CAM_URL);
  http.setTimeout(8000);
  addPreemptiveBasicAuth(http);
  code = http.GET();

  // Try 2: Digest fallback (common on some cameras)
  if (code == 401) {
    http.end();

    // Fetch challenge header
    String wwwAuth;
    {
      static const char* keys[] = {"WWW-Authenticate"};
      HTTPClient chal;
      chal.begin(IP_CAM_URL);
      chal.collectHeaders(keys, 1);
      chal.setTimeout(8000);
      int ccode = chal.GET();
      if (ccode > 0) {
        wwwAuth = chal.header("WWW-Authenticate");
      }
      chal.end();
    }

    DigestChallenge c = parseDigestChallenge(wwwAuth);
    if (c.ok) {
      String auth = buildDigestAuth(c, "GET", cam.path, String(IP_CAM_USER), String(IP_CAM_PASS));
      if (auth.length()) {
        http.begin(IP_CAM_URL);
        http.setTimeout(8000);
        http.addHeader("Authorization", auth);
        code = http.GET();
      }
    }
  }

  if (code != 200) {
    Serial.print("Camera IP GET falhou: ");
    Serial.println(code);
    http.end();
    return false;
  }

  int len = http.getSize();
  if (len <= 0) {
    Serial.println("Camera IP retornou imagem vazia.");
    http.end();
    return false;
  }

  uint8_t* buffer = (uint8_t*)ps_malloc((size_t)len);
  if (!buffer) {
    Serial.println("Sem memoria (ps_malloc) para snapshot.");
    http.end();
    return false;
  }

  WiFiClient* stream = http.getStreamPtr();
  int total = 0;
  while (http.connected() && total < len) {
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
  http.end();

  if (total != len) {
    Serial.printf("Download incompleto: %d/%d bytes\n", total, len);
    free(buffer);
    return false;
  }

  outBuf = buffer;
  outLen = total;
  return true;
}

static void writeAll(Stream& s, const uint8_t* buf, size_t len) {
  size_t off = 0;
  while (off < len) {
    size_t chunk = len - off;
    if (chunk > 1024) chunk = 1024;
    s.write(buf + off, chunk);
    off += chunk;
  }
}

static void uploadSnapshot(const uint8_t* buf, int len) {
  if (!ensureWiFi()) return;

  String base = String(SERVER_BASE);
  ParsedUrl u = parseHttpUrl(base);
  if (!u.ok) {
    Serial.println("Upload: SERVER_BASE invalido (precisa http:// ou https://).");
    return;
  }

  // Permite base com path (prefixo), ex: https://host/prefix
  String fullUploadUrl = joinPath(base, UPLOAD_PATH);
  ParsedUrl up = parseHttpUrl(fullUploadUrl);
  if (!up.ok) {
    Serial.println("Upload: URL final invalida.");
    return;
  }

  WiFiClient plain;
  WiFiClientSecure tls;
  Stream* sock = nullptr;

  if (up.https) {
    if (TLS_INSECURE) tls.setInsecure();
    if (!tls.connect(up.host.c_str(), up.port)) {
      Serial.println("Upload: falha conectando TLS.");
      return;
    }
    sock = &tls;
  } else {
    if (!plain.connect(up.host.c_str(), up.port)) {
      Serial.println("Upload: falha conectando.");
      return;
    }
    sock = &plain;
  }

  const String boundary = "RandomBoundary";
  const String head =
    "--" + boundary + "\r\n"
    "Content-Disposition: form-data; name=\"imageFile\"; filename=\"snapshot_relay.jpg\"\r\n"
    "Content-Type: image/jpeg\r\n\r\n";
  const String tail = "\r\n--" + boundary + "--\r\n";

  uint32_t totalLen = (uint32_t)len + head.length() + tail.length();

  sock->print(String("POST ") + up.path + " HTTP/1.1\r\n");
  sock->print(String("Host: ") + up.host + "\r\n");
  sock->print("Connection: close\r\n");
  sock->print(String("Content-Type: multipart/form-data; boundary=") + boundary + "\r\n");
  sock->print(String("Content-Length: ") + String(totalLen) + "\r\n");
  sock->print("\r\n");
  sock->print(head);
  writeAll(*sock, buf, (size_t)len);
  sock->print(tail);

  // Lê primeira linha da resposta (best-effort)
  uint32_t start = millis();
  while (millis() - start < 5000) {
    if (up.https ? tls.available() : plain.available()) break;
    delay(10);
  }

  String statusLine;
  if (up.https) statusLine = tls.readStringUntil('\n');
  else statusLine = plain.readStringUntil('\n');

  Serial.print("Upload ");
  Serial.print(fullUploadUrl);
  Serial.print(" -> ");
  Serial.println(statusLine.length() ? statusLine : "(sem resposta)");

  if (up.https) tls.stop();
  else plain.stop();
}

static void relayExternalImage() {
  if (!ensureWiFi()) return;

  uint32_t t0 = millis();
  Serial.println();
  Serial.println("--- INICIANDO PROCESSO (IP CAM RELAY) ---");
  Serial.println("1. Baixando snapshot da Camera IP...");

  uint8_t* buf = nullptr;
  int len = 0;
  if (!downloadSnapshot(buf, len)) {
    sendStatus("ERRO: falha ao baixar snapshot da camera IP");
    return;
  }
  uint32_t t1 = millis();
  Serial.printf("   OK: %d bytes\n", len);
  Serial.printf("   Tempo download: %lu ms\n", (unsigned long)(t1 - t0));

  Serial.println("2. Enviando para o servidor...");
  uploadSnapshot(buf, len);
  uint32_t t2 = millis();
  Serial.printf("   Tempo upload: %lu ms\n", (unsigned long)(t2 - t1));
  Serial.printf("   Tempo total ciclo: %lu ms\n", (unsigned long)(t2 - t0));

  free(buf);
}

void setup() {
  Serial.begin(115200);
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  WiFi.begin(ssid, password);
  Serial.print("Conectando WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi online. IP: ");
  Serial.println(WiFi.localIP());

  sendStatus("ESP32 online (ipcam-relay)");
}

void loop() {
  // Agenda o proximo ciclo contando a partir do INICIO do ciclo (nao soma tempo de processamento + delay).
  // Isso evita virar ~1 minuto quando download/upload levam 20-30s.
  if (nextRunAt == 0) nextRunAt = millis();
  if ((int32_t)(millis() - nextRunAt) >= 0) {
    nextRunAt = millis() + TIMER_DELAY_MS;
    relayExternalImage();
  }
}
