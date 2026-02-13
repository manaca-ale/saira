#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <WiFiUdp.h>
#include <HTTPClient.h>
#include <Preferences.h>
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
static uint32_t gCaptureFailStreak = 0;
static uint32_t gUploadOk = 0;
static uint32_t gUploadFail = 0;
static uint32_t gUploadFailStreak = 0;
static uint32_t gLastCaptureBytes = 0;
static uint32_t gLastQueueBytes = 0;
static uint32_t gCompactFailCount = 0;
static uint32_t gCompactSuccessCount = 0;
static uint32_t gWifiDownSince = 0;
static uint32_t gCaptureHoldUntil = 0;
static uint32_t gLastOtaGuardStatusAt = 0;
static uint32_t gBootAtMs = 0;
static uint32_t gLastCaptureOkAt = 0;
static uint32_t gLastUploadOkAt = 0;
static uint32_t gLastStatusOkAt = 0;
static uint32_t gLastRecoveryAt = 0;
static uint8_t  gRecoveryStage = 0;
static uint32_t gPendingRebootAt = 0;
static uint32_t gRebootReasonCode = 0;
static int      gCamLastHttpCode = -1;
static String   gCamLastAuthStage = "idle";
static String   gCamLastAuthHint = "none";
static String   gCamLastHost = "";
static String   gCamLastPath = "/snap.jpg";

static const uint32_t SAIRA_OTA_GUARD_WIFI_DOWN_MS = 30000;
static const uint32_t SAIRA_OTA_GUARD_HOLD_MS = 60000;
static const uint32_t SAIRA_RECOVERY_STEP_MS = 20000;
static const uint32_t SAIRA_CAPTURE_STALL_MS = 180000;
static const uint32_t SAIRA_HARD_STALL_REBOOT_MS = 600000;
static const uint32_t SAIRA_DISCOVER_COOLDOWN_MS = 20000;
static const uint32_t SAIRA_DISCOVER_FAST_COOLDOWN_MS = 8000;
static const uint32_t SAIRA_DISCOVER_BOOT_GRACE_MS = 90000;
static const uint32_t SAIRA_CAM_NVS_MIN_WRITE_GAP_MS = 30000;
static const uint32_t SAIRA_CAM_MIN_CAPTURE_INTERVAL_MS = 10000;
static const uint32_t SAIRA_DISCOVER_PROBE_BUDGET = 18;
static const uint32_t SAIRA_DISCOVER_PROBE_GAP_MS = 250;
static const uint32_t SAIRA_DISCOVER_MAX_WINDOW_MS = 7000;

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

static bool extractIpv4Host(const String& url, IPAddress& outIp) {
  ParsedUrl p = parseHttpUrl(url);
  if (!p.ok) return false;
  return outIp.fromString(p.host);
}

static String buildUrlWithHostPortPath(const IPAddress& host, uint16_t port, const String& path) {
  String out = "http://";
  out += host.toString();
  if (port != 80) {
    out += ":";
    out += String(port);
  }
  if (path.length() == 0 || path[0] != '/') out += "/";
  out += (path.length() ? path : "/snap.jpg");
  return out;
}

static String buildCameraSnapshotUrlForHost(const IPAddress& host, uint16_t detectedPort = 0) {
  ParsedUrl cam = parseHttpUrl(ipCamUrl);
  uint16_t port = 80;
  String path = "/snap.jpg";
  if (cam.ok) {
    port = cam.port ? cam.port : 80;
    path = cam.path.length() ? cam.path : String("/snap.jpg");
  }
  if (detectedPort != 0 && (!cam.ok || cam.port == 80)) {
    port = detectedPort;
  }
  return buildUrlWithHostPortPath(host, port, path);
}

static void sendStatus(const String& msg);

#if SAIRA_USE_ETHERNET
static Preferences gCamPrefs;
static bool gCamPrefsReady = false;
static String gLastKnownCameraUrl = "";
static String gCameraVendorHint = "unknown";
static uint32_t gLastCamNvsWriteAt = 0;

static bool sameSubnet24(const IPAddress& a, const IPAddress& b) {
  return (a[0] == b[0] && a[1] == b[1] && a[2] == b[2]);
}

static bool shouldPauseWiFiForTarget(const IPAddress& targetIp) {
#if SAIRA_ETH_WIFI_DUAL_MODE
  if (WiFi.status() != WL_CONNECTED) return false;
  if (!ETH.linkUp()) return false;
  IPAddress wifiIp = WiFi.localIP();
  IPAddress ethIp = ETH.localIP();
  if (wifiIp == INADDR_NONE || ethIp == INADDR_NONE) return false;
  return sameSubnet24(targetIp, wifiIp) && sameSubnet24(targetIp, ethIp);
#else
  (void)targetIp;
  return false;
#endif
}

struct ScopedWifiPause {
  bool active = false;
  ScopedWifiPause() = default;
  void pauseFor(const IPAddress& targetIp) {
    if (active) return;
    if (!shouldPauseWiFiForTarget(targetIp)) return;
    Serial.print("NET: conflito de rota Wi-Fi/Ethernet para ");
    Serial.print(targetIp);
    Serial.println("; pausando Wi-Fi durante acesso da camera.");
    WiFi.disconnect(false, false);
    delay(120);
    active = true;
  }
  explicit ScopedWifiPause(const IPAddress& targetIp) {
    pauseFor(targetIp);
  }
  ~ScopedWifiPause() {
    if (active) {
      WiFi.reconnect();
      Serial.println("NET: Wi-Fi retomado apos acesso da camera.");
    }
  }
};

static bool gEthStarted = false;
static bool gEthLinkReported = false;
static bool gEthBeginAttempted = false;
static bool gEthInitUnavailable = false;
static uint32_t gNextEthRetryAt = 0;
static uint32_t gNextWifiRetryAt = 0;
static uint32_t gEthBeginFailCount = 0;
static uint32_t gEthLastAttemptAt = 0;
static uint32_t gEthLastWarnAt = 0;
static String gEthLastError = "boot";
static uint8_t gDiscoverCursorHost = 2;
static uint32_t gDiscoverAttempts = 0;
static uint32_t gDiscoverHits = 0;
static uint32_t gDiscoverLastAt = 0;
static String gDiscoverLast = "none";
static uint32_t gNextDiscoverTryAt = 0;
static uint32_t gNextCamProbeAt = 0;

static bool strContainsNoCase(const String& text, const char* needle) {
  String t = text;
  String n = String(needle);
  t.toLowerCase();
  n.toLowerCase();
  return t.indexOf(n) >= 0;
}

static bool ensureCamPrefsReady() {
  if (gCamPrefsReady) return true;
  if (!gCamPrefs.begin("ipcam", false)) {
    Serial.println("NVS: falha abrindo namespace ipcam.");
    return false;
  }
  gCamPrefsReady = true;
  return true;
}

static void setCameraVendorHint(const String& hint) {
  if (!hint.length()) return;
  if (hint == gCameraVendorHint) return;
  gCameraVendorHint = hint;
}

static bool rememberLastKnownCameraUrl(const String& url, const char* source) {
  if (!url.length()) return false;
  if (url == gLastKnownCameraUrl) return true;

  const uint32_t now = millis();
  if (gLastCamNvsWriteAt != 0 &&
      (uint32_t)(now - gLastCamNvsWriteAt) < SAIRA_CAM_NVS_MIN_WRITE_GAP_MS) {
    gLastKnownCameraUrl = url;
    return true;
  }

  if (!ensureCamPrefsReady()) return false;
  if (!gCamPrefs.putString("last_url", url)) return false;
  gLastCamNvsWriteAt = now;
  gLastKnownCameraUrl = url;

  Serial.print("NVS: last_url atualizado (");
  Serial.print(source ? source : "unknown");
  Serial.print(") -> ");
  Serial.println(url);
  return true;
}

static void loadLastKnownCameraUrlFromNvs() {
  if (!ensureCamPrefsReady()) return;
  String saved = gCamPrefs.getString("last_url", "");
  saved.trim();
  if (!saved.length()) return;

  IPAddress savedIp;
  if (!extractIpv4Host(saved, savedIp)) return;

  gLastKnownCameraUrl = saved;
  ipCamUrl = saved;
  Serial.print("NVS: camera URL restaurada -> ");
  Serial.println(ipCamUrl);
}

static bool extractOnvifXAddr(const String& response, IPAddress& outIp, uint16_t& outPort) {
  int cursor = 0;
  while (true) {
    int pos = response.indexOf("http://", cursor);
    if (pos < 0) break;
    int end = pos;
    while (end < (int)response.length()) {
      char c = response[end];
      if (c == '<' || c == '"' || c == '\'' || c == ' ' || c == '\r' || c == '\n' || c == '\t') break;
      end++;
    }
    String url = response.substring(pos, end);
    ParsedUrl parsed = parseHttpUrl(url);
    if (parsed.ok) {
      IPAddress ip;
      if (ip.fromString(parsed.host)) {
        outIp = ip;
        outPort = parsed.port ? parsed.port : 80;
        if (strContainsNoCase(response, "xelplon")) {
          setCameraVendorHint("xelplon");
        } else if (strContainsNoCase(response, "networkvideotransmitter")) {
          setCameraVendorHint("onvif_nvt");
        }
        return true;
      }
    }
    cursor = end + 1;
  }
  return false;
}

static bool tryOnvifWsDiscovery(IPAddress& outIp, uint16_t& outPort, String& outReason) {
  outReason = "onvif_no_reply";
  outPort = 80;
  if (!ETH.linkUp() || ETH.localIP() == INADDR_NONE) {
    outReason = "onvif_eth_offline";
    return false;
  }

  WiFiUDP udp;
  IPAddress multicastIp(239, 255, 255, 250);
  uint16_t localPort = (uint16_t)(37020 + (esp_random() % 500));
  if (!udp.beginMulticast(multicastIp, localPort)) {
    outReason = "onvif_udp_bind_fail";
    return false;
  }

  String probe =
      "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
      "<e:Envelope xmlns:e=\"http://www.w3.org/2003/05/soap-envelope\" "
      "xmlns:w=\"http://schemas.xmlsoap.org/ws/2004/08/addressing\" "
      "xmlns:d=\"http://schemas.xmlsoap.org/ws/2005/04/discovery\" "
      "xmlns:dn=\"http://www.onvif.org/ver10/network/wsdl\">"
      "<e:Header>"
      "<w:MessageID>uuid:" + randomHex8() + randomHex8() + randomHex8() + "</w:MessageID>"
      "<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
      "<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>"
      "</e:Header>"
      "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
      "</e:Envelope>";

  bool sent = false;
  if (udp.beginPacket(multicastIp, 3702)) {
    sent = (udp.print(probe) > 0) && udp.endPacket();
  }

  if (!sent) {
    udp.stop();
    outReason = "onvif_send_fail";
    return false;
  }

  uint32_t deadline = millis() + 1200;
  while ((int32_t)(millis() - deadline) < 0) {
    int pktLen = udp.parsePacket();
    if (pktLen <= 0) {
      delay(5);
      continue;
    }

    String payload;
    payload.reserve((size_t)(pktLen > 1024 ? 1024 : pktLen));
    while (pktLen > 0) {
      uint8_t buf[192];
      int rd = udp.read(buf, (int)sizeof(buf));
      if (rd <= 0) break;
      payload.concat((const char*)buf, (unsigned int)rd);
      pktLen -= rd;
      if (payload.length() > 4096) break;
    }

    IPAddress hitIp;
    uint16_t hitPort = 80;
    if (extractOnvifXAddr(payload, hitIp, hitPort)) {
      outIp = hitIp;
      outPort = hitPort;
      outReason = "onvif_xaddr_hit";
      udp.stop();
      return true;
    }
  }

  udp.stop();
  return false;
}

static bool configureEthStaticFromCameraUrl() {
  ParsedUrl cam = parseHttpUrl(ipCamUrl);
  if (!cam.ok) return false;

  IPAddress camIp;
  if (!camIp.fromString(cam.host)) {
    Serial.println("NET: camera host nao eh IPv4, sem fallback estatico.");
    return false;
  }

  IPAddress wifiIp = WiFi.localIP();
  bool wifiSameSubnet = (wifiIp != INADDR_NONE &&
                         wifiIp[0] == camIp[0] &&
                         wifiIp[1] == camIp[1] &&
                         wifiIp[2] == camIp[2]);
  const uint8_t candidates[] = {20, 21, 22, 50, 99, 200};
  IPAddress local(camIp[0], camIp[1], camIp[2], 0);
  bool picked = false;
  for (size_t i = 0; i < sizeof(candidates); ++i) {
    uint8_t host = candidates[i];
    if (host == camIp[3]) continue;
    if (wifiSameSubnet && host == wifiIp[3]) continue;
    local = IPAddress(camIp[0], camIp[1], camIp[2], host);
    picked = true;
    break;
  }
  if (!picked) {
    local = IPAddress(camIp[0], camIp[1], camIp[2], 201);
  }
  IPAddress gateway(camIp[0], camIp[1], camIp[2], 1);
  IPAddress subnet = ((camIp[0] == 169 && camIp[1] == 254) ? IPAddress(255, 255, 0, 0)
                                                             : IPAddress(255, 255, 255, 0));

  if (!ETH.config(local, gateway, subnet, gateway, gateway)) {
    Serial.println("NET: ETH.config(estatico) falhou.");
    gEthLastError = "eth_config_static_fail";
    return false;
  }

  Serial.print("NET: ETH fallback estatico local=");
  Serial.print(local);
  Serial.print(" camera=");
  Serial.print(camIp);
  if (wifiIp != INADDR_NONE) {
    Serial.print(" wifi=");
    Serial.print(wifiIp);
  }
  Serial.println();
  return true;
}

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
    if (gEthInitUnavailable) {
      const uint32_t now = millis();
      if ((int32_t)(now - gEthLastWarnAt) >= 30000) {
        gEthLastWarnAt = now;
        Serial.println("NET: ETH.begin indisponivel neste boot (falha anterior).");
      }
      return false;
    }
    if (gEthBeginAttempted) return false;
    gEthBeginAttempted = true;
    gEthLastAttemptAt = millis();

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
      gEthBeginFailCount++;
      gEthLastError = "eth_begin_fail";
      gEthInitUnavailable = true;
      return false;
    }
    gEthStarted = true;
    gEthLastError = "eth_started";
  }

  uint32_t t0 = millis();
  while (!ETH.linkUp() && millis() - t0 < timeoutMs) {
    delay(200);
  }
  if (!ETH.linkUp()) {
    gEthLinkReported = false;
    Serial.println("NET: Ethernet sem link (timeout).");
    gEthLastError = "eth_link_timeout";
    return false;
  }

  uint32_t tIp0 = millis();
  while (ETH.localIP() == INADDR_NONE && millis() - tIp0 < timeoutMs) {
    delay(200);
  }
  if (ETH.localIP() == INADDR_NONE) {
    Serial.println("NET: ETH sem DHCP; tentando IP estatico baseado na camera...");
    if (configureEthStaticFromCameraUrl()) {
      uint32_t tStatic0 = millis();
      while (ETH.localIP() == INADDR_NONE && millis() - tStatic0 < 3000) {
        delay(100);
      }
    }
  }
  if (ETH.localIP() == INADDR_NONE) {
    Serial.println("NET: Ethernet link sem IP (DHCP/estatico).");
    gEthLastError = "eth_no_ip";
    return false;
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
  gEthLastError = "eth_ok";
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
    ethOk = (ETH.linkUp() && ETH.localIP() != INADDR_NONE);
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

static bool forceEnsureUplinkNow() {
#if SAIRA_ETH_WIFI_DUAL_MODE
  if (WiFi.status() == WL_CONNECTED) return true;
  gNextWifiRetryAt = millis() + (uint32_t)SAIRA_WIFI_RETRY_INTERVAL_MS;
  return connectWiFiUplink(7000);
#else
  return ensureUplinkNet();
#endif
}

static void updateOtaGuard() {
  if (WiFi.status() == WL_CONNECTED) {
    gWifiDownSince = 0;
    return;
  }

  const uint32_t now = millis();
  if (gWifiDownSince == 0) gWifiDownSince = now;
  if ((uint32_t)(now - gWifiDownSince) < SAIRA_OTA_GUARD_WIFI_DOWN_MS) return;

  // Keep OTA safe: when uplink is unstable for too long, pause camera workload
  // and focus on restoring Wi-Fi connectivity.
  gCaptureHoldUntil = now + SAIRA_OTA_GUARD_HOLD_MS;
  (void)forceEnsureUplinkNow();

  if ((int32_t)(now - gLastOtaGuardStatusAt) >= 30000) {
    gLastOtaGuardStatusAt = now;
    sendStatus("WARN ota_guard wifi_down_ms=" + String((uint32_t)(now - gWifiDownSince)) +
               " hold_ms=" + String(SAIRA_OTA_GUARD_HOLD_MS) +
               " heap=" + String(ESP.getFreeHeap()));
  }
}

static bool captureAllowedByOtaGuard() {
  updateOtaGuard();
  if (gCaptureHoldUntil == 0) return true;
  return ((int32_t)(millis() - gCaptureHoldUntil) >= 0);
}

static void scheduleSafeReboot(uint32_t delayMs, uint32_t reasonCode) {
  if (gPendingRebootAt != 0) return;
  gPendingRebootAt = millis() + delayMs;
  gRebootReasonCode = reasonCode;
  sendStatus("WARN auto_reboot_scheduled reason=" + String(reasonCode) +
             " delay_ms=" + String(delayMs) +
             " cap_fail_streak=" + String(gCaptureFailStreak) +
             " up_fail_streak=" + String(gUploadFailStreak));
}

static void maybeRunSafeReboot() {
  if (gPendingRebootAt == 0) return;
  if ((int32_t)(millis() - gPendingRebootAt) < 0) return;

  Serial.print("WATCHDOG: reboot controlado. reason=");
  Serial.println((unsigned long)gRebootReasonCode);
  delay(150);
  ESP.restart();
}

static bool ensureCameraNet() {
#if SAIRA_ETH_WIFI_DUAL_MODE
  if (ETH.linkUp() && ETH.localIP() != INADDR_NONE) return true;
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
               " eth_ip=" + ETH.localIP().toString() +
               " eth_started=" + String(gEthStarted ? 1 : 0) +
               " eth_init_na=" + String(gEthInitUnavailable ? 1 : 0) +
               " eth_begin_fail=" + String(gEthBeginFailCount) +
               " eth_err=" + gEthLastError +
               " disc_try=" + String(gDiscoverAttempts) +
               " disc_hit=" + String(gDiscoverHits) +
               " disc_last=" + gDiscoverLast +
               " cam_vendor=" + gCameraVendorHint +
               " cam_last=" + (gLastKnownCameraUrl.length() ? gLastKnownCameraUrl : String("none")) +
#endif
               " cap_ok=" + String(gCaptureOk) +
               " cap_fail=" + String(gCaptureFail) +
               " up_ok=" + String(gUploadOk) +
               " up_fail=" + String(gUploadFail) +
               " up_fail_streak=" + String(gUploadFailStreak) +
               " wifi_down_ms=" + String(gWifiDownSince ? (uint32_t)(millis() - gWifiDownSince) : 0) +
               " cap_hold=" + String((gCaptureHoldUntil && (int32_t)(millis() - gCaptureHoldUntil) < 0) ? 1 : 0) +
               " rec_stage=" + String(gRecoveryStage) +
               " rb_pending=" + String(gPendingRebootAt ? 1 : 0) +
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
  if (code == 200) {
    gLastStatusOkAt = millis();
  }

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

#if SAIRA_USE_ETHERNET
static String buildHttpUrl(const IPAddress& ip, uint16_t port, const String& path) {
  String url = "http://";
  url += ip.toString();
  if (port != 80) {
    url += ":";
    url += String(port);
  }
  if (path.length() == 0 || path[0] != '/') url += "/";
  url += path;
  return url;
}

static bool probeCameraEndpoint(const IPAddress& ip,
                                uint16_t port,
                                const String& path,
                                int32_t timeoutMs,
                                int& outCode,
                                String& outWwwAuth,
                                String& outServer) {
  outCode = -1;
  outWwwAuth = "";
  outServer = "";

  WiFiClient cli;
  HTTPClient http;
  String url = buildHttpUrl(ip, port, path);
  if (!http.begin(cli, url)) return false;

  static const char* hdrKeys[] = {"WWW-Authenticate", "Server"};
  http.collectHeaders(hdrKeys, 2);
  http.setConnectTimeout(timeoutMs);
  http.setTimeout(timeoutMs);
  addPreemptiveBasicAuth(http);
  outCode = http.GET();
  outWwwAuth = http.header("WWW-Authenticate");
  outServer = http.header("Server");
  http.end();

  if (outCode == 200) return true;

  // Keep discovery auth flow aligned with legacy capture flow:
  // try Digest when endpoint challenges with WWW-Authenticate.
  if ((outCode == 401 || outCode == 403) && outWwwAuth.length()) {
    DigestChallenge c = parseDigestChallenge(outWwwAuth);
    if (c.ok) {
      uint32_t probeNc = 1;
      String auth = buildDigestAuthWithNc(c, "GET", path, ipCamUser, ipCamPass, probeNc);
      if (auth.length()) {
        WiFiClient digestCli;
        HTTPClient digestHttp;
        if (digestHttp.begin(digestCli, url)) {
          digestHttp.collectHeaders(hdrKeys, 2);
          digestHttp.setConnectTimeout(timeoutMs);
          digestHttp.setTimeout(timeoutMs);
          digestHttp.addHeader("Authorization", auth);
          outCode = digestHttp.GET();
          outWwwAuth = digestHttp.header("WWW-Authenticate");
          outServer = digestHttp.header("Server");
          digestHttp.end();
          if (outCode == 200) return true;
        }
      }
    }
  }

  return false;
}

static String authHintFromHeader(const String& header) {
  if (!header.length()) return "none";
  String h = header;
  h.toLowerCase();
  if (h.indexOf("digest") >= 0) return "digest";
  if (h.indexOf("basic") >= 0) return "basic";
  return "other";
}

static bool configureEthStaticSubnet(uint8_t a, uint8_t b, uint8_t c, IPAddress& outLocal, bool linkLocal16 = false) {
  IPAddress wifiIp = WiFi.localIP();
  const bool wifiSameSubnet = (wifiIp != INADDR_NONE &&
                               wifiIp[0] == a &&
                               wifiIp[1] == b &&
                               wifiIp[2] == c);
  const uint8_t localCandidates[] = {20, 21, 22, 50, 99, 200, 210};
  uint8_t chosenHost = 20;
  for (size_t i = 0; i < sizeof(localCandidates); ++i) {
    uint8_t host = localCandidates[i];
    if (wifiSameSubnet && host == wifiIp[3]) continue;
    chosenHost = host;
    break;
  }

  IPAddress local(a, b, c, chosenHost);
  IPAddress gateway(a, b, c, 1);
  IPAddress subnet = linkLocal16 ? IPAddress(255, 255, 0, 0) : IPAddress(255, 255, 255, 0);
  if (!ETH.config(local, gateway, subnet, gateway, gateway)) return false;
  delay(120);
  outLocal = local;
  return true;
}

static bool discoverCameraEndpoint(String& outUrl, String& outReason) {
  outUrl = "";
  outReason = "discover_not_found";

  if (!ETH.linkUp() || ETH.localIP() == INADDR_NONE) {
    outReason = "discover_eth_offline";
    return false;
  }

  ParsedUrl cam = parseHttpUrl(ipCamUrl);
  if (!cam.ok) {
    outReason = "discover_bad_ip_cam_url";
    return false;
  }

  auto updateVendorHint = [&](const String& wwwAuth, const String& server) {
    if (strContainsNoCase(wwwAuth, "xelplon") || strContainsNoCase(server, "xelplon")) {
      setCameraVendorHint("xelplon");
    } else if (strContainsNoCase(wwwAuth, "hikvision") || strContainsNoCase(server, "hikvision")) {
      setCameraVendorHint("hikvision");
    } else if (strContainsNoCase(wwwAuth, "dahua") || strContainsNoCase(server, "dahua")) {
      setCameraVendorHint("dahua");
    } else if (strContainsNoCase(wwwAuth, "basic") && gCameraVendorHint == "unknown") {
      setCameraVendorHint("basic_auth");
    }
  };

  auto tryProbe = [&](const IPAddress& ip, uint16_t port, const String& path, const char* reasonTag) -> bool {
    if ((uint32_t)(millis() - gDiscoverLastAt) > SAIRA_DISCOVER_MAX_WINDOW_MS) {
      outReason = "discover_time_budget_exceeded";
      return false;
    }

    const uint32_t now = millis();
    if (gNextCamProbeAt != 0 && (int32_t)(now - gNextCamProbeAt) < 0) {
      delay((uint32_t)(gNextCamProbeAt - now));
    }

    int code = -1;
    String wwwAuth;
    String server;
    if (!probeCameraEndpoint(ip, port, path, 220, code, wwwAuth, server)) {
      gNextCamProbeAt = millis() + SAIRA_DISCOVER_PROBE_GAP_MS;
      return false;
    }

    updateVendorHint(wwwAuth, server);
    outUrl = buildHttpUrl(ip, port, path);
    outReason = String(reasonTag) + "_" + String(code) + "_" + ip.toString();
    if (gCameraVendorHint == "xelplon") {
      outReason += "_xelplon";
    }
    rememberLastKnownCameraUrl(outUrl, reasonTag);
    gNextCamProbeAt = millis() + SAIRA_DISCOVER_PROBE_GAP_MS;
    return true;
  };

  const uint16_t camPort = cam.port ? cam.port : 80;
  const String camPath = cam.path.length() ? cam.path : String("/snap.jpg");

  // Endpoint/path/auth come from the stable Wi-Fi version. In Ethernet mode we only
  // discover the host IP and reuse the same camera URL path/port/auth.
  auto tryHostKnown = [&](const IPAddress& ip, uint16_t preferredPort, const char* reasonTag) -> bool {
    uint16_t portToUse = preferredPort ? preferredPort : camPort;
    return tryProbe(ip, portToUse, camPath, reasonTag);
  };

  IPAddress lastIp;
  if (extractIpv4Host(gLastKnownCameraUrl, lastIp)) {
    if (tryHostKnown(lastIp, camPort, "discover_last_known")) return true;
  }

  IPAddress onvifIp;
  uint16_t onvifPort = 80;
  String onvifReason;
  if (tryOnvifWsDiscovery(onvifIp, onvifPort, onvifReason)) {
    if (tryHostKnown(onvifIp, onvifPort, "discover_onvif")) return true;
    outReason = "discover_onvif_snapshot_miss";
  }

  struct SubnetPrefix {
    uint8_t a;
    uint8_t b;
    uint8_t c;
    bool linkLocal16;
  };
  SubnetPrefix subnetCandidates[10];
  int subnetCount = 0;
  auto addSubnet = [&](uint8_t a, uint8_t b, uint8_t c, bool linkLocal16 = false) {
    for (int i = 0; i < subnetCount; ++i) {
      if (subnetCandidates[i].a == a &&
          subnetCandidates[i].b == b &&
          subnetCandidates[i].c == c &&
          subnetCandidates[i].linkLocal16 == linkLocal16) {
        return;
      }
    }
    if (subnetCount < (int)(sizeof(subnetCandidates) / sizeof(subnetCandidates[0]))) {
      subnetCandidates[subnetCount++] = {a, b, c, linkLocal16};
    }
  };

  IPAddress ethIp = ETH.localIP();
  addSubnet(ethIp[0], ethIp[1], ethIp[2], false);

  IPAddress wifiIp = WiFi.localIP();
  if (wifiIp != INADDR_NONE) {
    addSubnet(wifiIp[0], wifiIp[1], wifiIp[2], false);
  }

  IPAddress camIpCfg;
  const bool cfgIsIp = camIpCfg.fromString(cam.host);
  if (cfgIsIp) {
    addSubnet(camIpCfg[0], camIpCfg[1], camIpCfg[2], false);
    if (tryHostKnown(camIpCfg, camPort, "discover_config_ip")) return true;
  }

  if (extractIpv4Host(gLastKnownCameraUrl, lastIp)) {
    addSubnet(lastIp[0], lastIp[1], lastIp[2], false);
  }

  addSubnet(192, 168, 1, false);
  addSubnet(192, 168, 0, false);
  addSubnet(10, 0, 0, false);
  addSubnet(169, 254, 20, true);

  if (subnetCount <= 0) {
    outReason = "discover_no_subnet";
    return false;
  }

  String lastReason = "discover_scan_empty";
  int probeBudget = (int)SAIRA_DISCOVER_PROBE_BUDGET;
  int subnetWindow = subnetCount < 3 ? subnetCount : 3;

  int subnetStart = 0;
  if (gDiscoverAttempts > 0) {
    subnetStart = (int)((gDiscoverAttempts - 1) % (uint32_t)subnetCount);
  }

  for (int s = 0; s < subnetWindow && probeBudget > 0; ++s) {
    int idx = (subnetStart + s) % subnetCount;
    SubnetPrefix targetSubnet = subnetCandidates[idx];

    IPAddress ethNow = ETH.localIP();
    bool sameSubnetNow = (ethNow[0] == targetSubnet.a && ethNow[1] == targetSubnet.b);
    if (!targetSubnet.linkLocal16) {
      sameSubnetNow = sameSubnetNow && (ethNow[2] == targetSubnet.c);
    }
    if (!sameSubnetNow) {
      IPAddress newLocal;
      if (configureEthStaticSubnet(targetSubnet.a, targetSubnet.b, targetSubnet.c, newLocal, targetSubnet.linkLocal16)) {
        Serial.print("DISCOVER: ETH subnet -> ");
        Serial.println(newLocal);
        gEthLastError = "discover_eth_subnet_switch";
      } else {
        lastReason = "discover_eth_reconfig_fail";
        continue;
      }
    }

    IPAddress onvifSubnetIp;
    uint16_t onvifSubnetPort = 80;
    String onvifSubnetReason;
    if (tryOnvifWsDiscovery(onvifSubnetIp, onvifSubnetPort, onvifSubnetReason)) {
      if (tryHostKnown(onvifSubnetIp, onvifSubnetPort, "discover_onvif_subnet")) return true;
    }

    IPAddress baseIp(targetSubnet.a, targetSubnet.b, targetSubnet.c, 1);
    bool used[256];
    memset(used, 0, sizeof(used));

    const bool wifiSameSubnet = (wifiIp != INADDR_NONE && sameSubnet24(wifiIp, baseIp));
    const uint8_t avoidWifiHost = wifiSameSubnet ? wifiIp[3] : 0;
    const uint8_t avoidEthHost = ETH.localIP()[3];

    uint8_t candidates[26];
    int candidateCount = 0;
    auto addCandidate = [&](uint8_t host) {
      if (host <= 1 || host >= 255) return;
      if (host == avoidEthHost) return;
      if (wifiSameSubnet && host == avoidWifiHost) return;
      if (used[host]) return;
      used[host] = true;
      if (candidateCount < (int)(sizeof(candidates))) {
        candidates[candidateCount++] = host;
      }
    };

    if (cfgIsIp && sameSubnet24(camIpCfg, baseIp)) addCandidate(camIpCfg[3]);

    const uint8_t preferredHosts[] = {
        142, 141, 140, 139, 138, 120, 110, 108, 100, 99, 90, 64, 50, 30, 22, 21, 20, 10, 200};
    for (size_t i = 0; i < sizeof(preferredHosts); ++i) addCandidate(preferredHosts[i]);
    for (int i = 0; i < 6; ++i) {
      addCandidate(gDiscoverCursorHost);
      gDiscoverCursorHost++;
      if (gDiscoverCursorHost < 2 || gDiscoverCursorHost >= 255) gDiscoverCursorHost = 2;
    }

    if (candidateCount <= 0) {
      lastReason = "discover_no_candidates";
      continue;
    }

    ScopedWifiPause pauseGuard(IPAddress(baseIp[0], baseIp[1], baseIp[2], candidates[0]));
    for (int i = 0; i < candidateCount && probeBudget > 0; ++i) {
      IPAddress ip(baseIp[0], baseIp[1], baseIp[2], candidates[i]);
      probeBudget--;
      if (tryHostKnown(ip, camPort, "discover_scan_host")) return true;
    }

    lastReason = String("discover_scan_exhausted_") +
                 String(baseIp[0]) + "." + String(baseIp[1]) + "." + String(baseIp[2]);
  }

  outReason = lastReason;
  return false;
}
#endif

static bool downloadSnapshot(uint8_t*& outBuf, int& outLen) {
  outBuf = nullptr;
  outLen = 0;

  uint32_t t0 = millis();
  ParsedUrl cam = parseHttpUrl(ipCamUrl);
  if (!cam.ok) {
    gCamLastAuthStage = "bad_url";
    gCamLastHttpCode = -1;
    gCamLastAuthHint = "none";
    Serial.println("IP_CAM_URL invalido (precisa http://...).");
    return false;
  }
  gCamLastHost = cam.host;
  gCamLastPath = cam.path.length() ? cam.path : String("/snap.jpg");
  gCamLastAuthStage = "start";
  gCamLastHttpCode = -1;
  gCamLastAuthHint = "none";
  uint32_t tParse = sairaMsSince(t0);

#if SAIRA_USE_ETHERNET
  ScopedWifiPause camRoutePause;
  IPAddress camHostIp;
  if (camHostIp.fromString(cam.host)) {
    camRoutePause.pauseFor(camHostIp);
  }
#endif

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
      gCamLastAuthStage = "digest_cached";
      camDisconnect();
      if (camHttp.begin(camClient, ipCamUrl)) {
        static const char* camHdrKeys[] = {"WWW-Authenticate"};
        camHttp.collectHeaders(camHdrKeys, 1);
        camConnected = true;
        camHttp.setTimeout(8000);
        camHttp.addHeader("Connection", "keep-alive");
        camHttp.addHeader("Authorization", auth);
        uint32_t tReq0 = millis();
        code = camHttp.GET();
        gCamLastHttpCode = code;
        gCamLastAuthHint = authHintFromHeader(camHttp.header("WWW-Authenticate"));
        tHttpTotal += sairaMsSince(tReq0);
      }
    }

    // Nonce expired? Server returns 401 -> re-challenge below
    if (code == 401 || code == 403) {
      gCamLastAuthStage = "digest_cached_expired";
      Serial.println("Digest nonce expirado, re-autenticando...");
      cachedDigest = DigestChallenge{};
      digestNc = 0;
      camDisconnect();
      code = -1; // fall through to full auth
    }
  }

  if (code != 200 && !cachedDigest.ok) {
    // Try 1: Basic (preemptive) with keep-alive
    gCamLastAuthStage = "basic_preemptive";
    camDisconnect();
    if (camHttp.begin(camClient, ipCamUrl)) {
      static const char* camHdrKeys[] = {"WWW-Authenticate"};
      camHttp.collectHeaders(camHdrKeys, 1);
      camConnected = true;
      camHttp.setTimeout(8000);
      camHttp.addHeader("Connection", "keep-alive");
      addPreemptiveBasicAuth(camHttp);
      uint32_t tReq0 = millis();
      code = camHttp.GET();
      gCamLastHttpCode = code;
      gCamLastAuthHint = authHintFromHeader(camHttp.header("WWW-Authenticate"));
      tHttpTotal += sairaMsSince(tReq0);
    }

    // Try 2: Digest fallback
    if (code == 401 || code == 403) {
      gCamLastAuthStage = "digest_challenge";
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
        gCamLastHttpCode = ccode;
        tChallenge = sairaMsSince(tCh0);
        tHttpTotal += tChallenge;
        if (ccode > 0) {
          wwwAuth = chalHttp.header("WWW-Authenticate");
          gCamLastAuthHint = authHintFromHeader(wwwAuth);
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
          gCamLastAuthStage = "digest_retry";
          if (camHttp.begin(camClient, ipCamUrl)) {
            static const char* camHdrKeys[] = {"WWW-Authenticate"};
            camHttp.collectHeaders(camHdrKeys, 1);
            camConnected = true;
            camHttp.setTimeout(8000);
            camHttp.addHeader("Connection", "keep-alive");
            camHttp.addHeader("Authorization", auth);
            uint32_t tReq0 = millis();
            code = camHttp.GET();
            gCamLastHttpCode = code;
            gCamLastAuthHint = authHintFromHeader(camHttp.header("WWW-Authenticate"));
            tHttpTotal += sairaMsSince(tReq0);
          }
        }
      } else {
        gCamLastAuthStage = "digest_parse_fail";
      }
    }
  }

  if (code != 200) {
    gCamLastHttpCode = code;
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
    gCamLastAuthStage = "empty_body";
    gCamLastHttpCode = code;
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

#if SAIRA_USE_ETHERNET
  IPAddress camIpOk;
  if (camIpOk.fromString(cam.host)) {
    String stableUrl = buildUrlWithHostPortPath(camIpOk, cam.port ? cam.port : 80, cam.path);
    (void)rememberLastKnownCameraUrl(stableUrl, "capture_ok");
  }
#endif

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
  while (millis() - tWait0 < 12000) {
    if (up.https ? tls.available() : plain.available()) break;
    delay(10);
  }
  uint32_t tWait = sairaMsSince(tWait0);

  String statusLine;
  if (up.https) {
    if (tls.available()) statusLine = tls.readStringUntil('\n');
  } else {
    if (plain.available()) statusLine = plain.readStringUntil('\n');
  }
  statusLine.trim();
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
static const int IMAGE_QUEUE_MAX = 8;
static const uint8_t IMAGE_UPLOAD_MAX_RETRIES = 3;

struct QueuedImage {
    uint8_t* data;       // ponteiro PSRAM (ps_malloc)
    int      length;     // tamanho JPEG em bytes
    uint32_t capturedAt; // millis() da captura
    uint8_t  retryCount; // tentativas de upload ja feitas
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
    imageQueue[queueTail].retryCount = 0;
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
    imageQueue[queueHead] = {nullptr, 0, 0, 0};
    queueHead = (queueHead + 1) % IMAGE_QUEUE_MAX;
    queueCount--;
    xSemaphoreGive(queueMutex);
    return true;
}

static bool queueRequeue(const QueuedImage& in) {
    if (!in.data || in.length <= 0) return false;
    if (xSemaphoreTake(queueMutex, pdMS_TO_TICKS(1000)) != pdTRUE) {
        Serial.println("QUEUE: timeout obtendo mutex (requeue)");
        return false;
    }
    if (queueCount >= IMAGE_QUEUE_MAX) {
        free(imageQueue[queueHead].data);
        queueHead = (queueHead + 1) % IMAGE_QUEUE_MAX;
        queueCount--;
        Serial.println("QUEUE: descartou imagem mais antiga (fila cheia/requeue)");
    }
    imageQueue[queueTail] = in;
    queueTail = (queueTail + 1) % IMAGE_QUEUE_MAX;
    queueCount++;
    Serial.printf("QUEUE: re-enfileirou (%d bytes), retry=%u, total=%d\n",
                  in.length, (unsigned int)in.retryCount, queueCount);
    xSemaphoreGive(queueMutex);
    return true;
}

#if SAIRA_USE_ETHERNET
static void maybeFieldRecovery();
#endif

// ---- Upload task (runs on core 0, parallel to capture on core 1) ----
static void uploadTask(void* /*param*/) {
    Serial.println("UPLOAD_TASK: iniciada no core 0");
    for (;;) {
        updateOtaGuard();
        if (queueCount > 0) {
            QueuedImage img;
            if (queuePop(img)) {
                uint32_t now = millis();
                if (img.capturedAt) {
                    sairaPrintMs("queue_delay", (uint32_t)(now - img.capturedAt));
                }
                if (!ensureUplinkNet()) {
                    // Uplink indisponivel agora: nao perder frame, tentar de novo no proximo ciclo.
                    if (!queueRequeue(img)) {
                        free(img.data);
                        gUploadFail++;
                    }
                    vTaskDelay(pdMS_TO_TICKS(200));
                    continue;
                }
                Serial.printf("\n--- UPLOAD (fila restante: %d) ---\n", queueCount);
                if (uploadSnapshot(img.data, img.length)) {
                    gUploadOk++;
                    gUploadFailStreak = 0;
                    gLastUploadOkAt = millis();
                    free(img.data);
                } else {
                    gUploadFailStreak++;
                    img.retryCount++;
                    if (img.retryCount < IMAGE_UPLOAD_MAX_RETRIES) {
                        Serial.printf("UPLOAD: falhou, reagendando retry=%u\n", (unsigned int)img.retryCount);
                        (void)forceEnsureUplinkNow();
                        if (!queueRequeue(img)) {
                            free(img.data);
                            gUploadFail++;
                        }
                    } else {
                        gUploadFail++;
                        sendStatus("ERR upload drop net=" + String(sairaNetKind()) +
                                   " wifi=" + String((WiFi.status() == WL_CONNECTED) ? 1 : 0) +
                                   " retry=" + String(img.retryCount) +
                                   " q=" + String(queueCount) +
                                   " heap=" + String(ESP.getFreeHeap()));
                        free(img.data);
                    }
                }
            }
        }
#if SAIRA_USE_ETHERNET
        maybeFieldRecovery();
#endif
        maybeRunSafeReboot();
        maybeSendRemoteDebug();
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

#if SAIRA_USE_ETHERNET
static void maybeAutoDiscoverCamera() {
  const uint32_t now = millis();
  const bool noCaptureSinceBoot =
      (gCaptureOk == 0 && (uint32_t)(now - gBootAtMs) > SAIRA_DISCOVER_BOOT_GRACE_MS);
  const bool captureStalled =
      (gLastCaptureOkAt != 0 && (uint32_t)(now - gLastCaptureOkAt) > (SAIRA_CAPTURE_STALL_MS / 2));
  const bool shouldProbe =
      (gCaptureFailStreak >= 2) || noCaptureSinceBoot || captureStalled;
  if (!shouldProbe) return;
  if (!ETH.linkUp() || ETH.localIP() == INADDR_NONE) return;

  uint32_t cooldown = SAIRA_DISCOVER_COOLDOWN_MS;
  if (gCaptureFailStreak >= 8 || noCaptureSinceBoot) {
    cooldown = SAIRA_DISCOVER_FAST_COOLDOWN_MS;
  }
  if (gNextDiscoverTryAt != 0 && (int32_t)(now - gNextDiscoverTryAt) < 0) return;
  gNextDiscoverTryAt = now + cooldown;
  gDiscoverLastAt = now;
  gDiscoverAttempts++;

  String discoveredUrl;
  String reason;
  Serial.println("DISCOVER: iniciando varredura de camera na LAN Ethernet...");
  bool found = discoverCameraEndpoint(discoveredUrl, reason);
  gDiscoverLast = reason;

  if (!found) {
    Serial.print("DISCOVER: camera nao encontrada (");
    Serial.print(reason);
    Serial.println(").");
    sendStatus("WARN camera_discovery not_found reason=" + reason +
               " eth_ip=" + ETH.localIP().toString() +
               " fail_streak=" + String(gCaptureFailStreak) +
               " cooldown_ms=" + String(cooldown));
    return;
  }

  gDiscoverHits++;
  if (discoveredUrl != ipCamUrl) {
    Serial.print("DISCOVER: camera encontrada em ");
    Serial.println(discoveredUrl);
    ipCamUrl = discoveredUrl;
    cachedDigest = DigestChallenge{};
    digestNc = 0;
    camDisconnect();
    sendStatus("CFG camera_discovered url=" + discoveredUrl +
               " tries=" + String(gDiscoverAttempts) +
               " hits=" + String(gDiscoverHits));
  } else {
    Serial.print("DISCOVER: camera confirmada em ");
    Serial.println(discoveredUrl);
  }
}

static void maybeFieldRecovery() {
  const uint32_t now = millis();
  if ((uint32_t)(now - gBootAtMs) < 60000) return;  // grace period after boot

  const bool captureStalled =
      (gCaptureFailStreak >= 8) ||
      (gLastCaptureOkAt != 0 && (uint32_t)(now - gLastCaptureOkAt) > SAIRA_CAPTURE_STALL_MS);
  const bool uploadStalled = (gUploadFailStreak >= 8);

  if (!captureStalled && !uploadStalled) {
    gRecoveryStage = 0;
    return;
  }

  if ((int32_t)(now - gLastRecoveryAt) < (int32_t)SAIRA_RECOVERY_STEP_MS) return;
  gLastRecoveryAt = now;

  switch (gRecoveryStage) {
    case 0:
      Serial.println("RECOVERY: stage0 reset camera session.");
      camDisconnect();
      cachedDigest = DigestChallenge{};
      digestNc = 0;
      gEthLastError = "recovery_stage0_cam_reset";
      break;
    case 1:
      Serial.println("RECOVERY: stage1 force discovery.");
      gNextDiscoverTryAt = 0;
      maybeAutoDiscoverCamera();
      gEthLastError = "recovery_stage1_discovery";
      break;
    case 2:
      Serial.println("RECOVERY: stage2 reapply ETH static from camera URL.");
      (void)configureEthStaticFromCameraUrl();
      (void)ensureCameraNet();
      gEthLastError = "recovery_stage2_eth_reapply";
      break;
    case 3:
      Serial.println("RECOVERY: stage3 hold capture and restore Wi-Fi uplink.");
      gCaptureHoldUntil = now + 120000;
      (void)forceEnsureUplinkNow();
      gEthLastError = "recovery_stage3_uplink";
      break;
    default:
      Serial.println("RECOVERY: stage4 final watchdog decision.");
      if (gLastCaptureOkAt != 0 &&
          (uint32_t)(now - gLastCaptureOkAt) > SAIRA_HARD_STALL_REBOOT_MS) {
        scheduleSafeReboot(8000, 904);
      } else if (gLastCaptureOkAt == 0 &&
                 (uint32_t)(now - gBootAtMs) > SAIRA_HARD_STALL_REBOOT_MS) {
        scheduleSafeReboot(8000, 905);
      }
      gEthLastError = "recovery_stage4_watchdog";
      break;
  }

  sendStatus("WARN recovery stage=" + String(gRecoveryStage) +
             " cap_fail_streak=" + String(gCaptureFailStreak) +
             " up_fail_streak=" + String(gUploadFailStreak) +
             " eth_ip=" + ETH.localIP().toString());
  if (gRecoveryStage < 4) gRecoveryStage++;
}
#endif

void setup() {
  Serial.begin(115200);
#if defined(RTC_CNTL_BROWN_OUT_REG)
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
#endif

#if SAIRA_USE_ETHERNET
  loadLastKnownCameraUrlFromNvs();
#endif
  if (timerDelayMs < SAIRA_CAM_MIN_CAPTURE_INTERVAL_MS) {
    timerDelayMs = SAIRA_CAM_MIN_CAPTURE_INTERVAL_MS;
    Serial.print("CFG: TIMER_DELAY_MS ajustado para minimo seguro=");
    Serial.println((unsigned long)timerDelayMs);
  }

  Serial.print("Conectando rede");
  if (!connectBootNetwork(30000)) {
    Serial.println("NET: sem conectividade inicial; seguindo em modo degradado (OTA/rede continuam tentando).");
  }
  gBootAtMs = millis();
  gLastCaptureOkAt = gBootAtMs;
  gLastUploadOkAt = gBootAtMs;
  gLastStatusOkAt = gBootAtMs;

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
static uint32_t nextCameraNetWarnAt = 0;

void loop() {
  sairaMaybeCheckOta();

  // Remote config (manter logica existente)
  auto applyFn = +[](const String& key, const String& value) -> bool {
    bool changed = false;
    String k = key; k.toLowerCase();
    if (k == "timer_delay_ms") {
      long v = value.toInt();
      if (v >= 1000) {
        uint32_t requested = (uint32_t)v;
        uint32_t safe = requested < SAIRA_CAM_MIN_CAPTURE_INTERVAL_MS
                            ? SAIRA_CAM_MIN_CAPTURE_INTERVAL_MS
                            : requested;
        if (safe != timerDelayMs) {
          timerDelayMs = safe;
          changed = true;
        }
        if (safe != requested) {
          Serial.print("CFG: timer_delay_ms baixo; clamped para ");
          Serial.println((unsigned long)safe);
        }
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

    if (!captureAllowedByOtaGuard()) {
      if ((int32_t)(millis() - gLastOtaGuardStatusAt) >= 10000) {
        gLastOtaGuardStatusAt = millis();
        Serial.println("OTA_GUARD: captura pausada para preservar uplink/OTA.");
      }
    } else if (ensureCameraNet()) {
      uint8_t* buf = nullptr;
      int len = 0;
      Serial.println("\n--- CAPTURA ---");
      uint32_t tCap0 = millis();
      if (downloadSnapshot(buf, len)) {
        gCaptureOk++;
        gCaptureFailStreak = 0;
        gLastCaptureOkAt = millis();
        gRecoveryStage = 0;
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
        gCaptureFailStreak++;
        sairaPrintMs("capture_total", sairaMsSince(tCap0));
        Serial.println("   ERRO: falha na captura");
        sendStatus("ERR captura falhou net=" + String(sairaNetKind()) +
#if SAIRA_USE_ETHERNET
                   " eth_ip=" + ETH.localIP().toString() +
                   " eth_link=" + String(ETH.linkUp() ? 1 : 0) +
                   " eth_err=" + gEthLastError +
#endif
                   " cam_code=" + String(gCamLastHttpCode) +
                   " cam_stage=" + gCamLastAuthStage +
                   " cam_auth=" + gCamLastAuthHint +
                   " cam_host=" + gCamLastHost +
                   " cam_path=" + gCamLastPath +
                   " fail_streak=" + String(gCaptureFailStreak) +
                   " heap=" + String(ESP.getFreeHeap()) +
                   " psram=" + String(ESP.getFreePsram()));
#if SAIRA_USE_ETHERNET
        maybeAutoDiscoverCamera();
#endif
      }
    } else {
      const uint32_t now = millis();
      if (nextCameraNetWarnAt == 0 || (int32_t)(now - nextCameraNetWarnAt) >= 0) {
        nextCameraNetWarnAt = now + 30000;
#if SAIRA_USE_ETHERNET
        Serial.print("CAPTURA: rede da camera indisponivel. eth_link=");
        Serial.print(ETH.linkUp() ? 1 : 0);
        Serial.print(" eth_ip=");
        Serial.print(ETH.localIP());
        Serial.print(" err=");
        Serial.println(gEthLastError);
        sendStatus("WARN camera_net_offline eth=" + String(ETH.linkUp() ? 1 : 0) +
                   " eth_ip=" + ETH.localIP().toString() +
                   " err=" + gEthLastError +
                   " begin_fail=" + String(gEthBeginFailCount));
#else
        Serial.println("CAPTURA: rede da camera indisponivel.");
#endif
      }
#if SAIRA_USE_ETHERNET
      maybeAutoDiscoverCamera();
#endif
    }
  }

#if SAIRA_USE_ETHERNET
  maybeFieldRecovery();
#endif
  maybeRunSafeReboot();
  maybeSendRemoteDebug();
  // Upload agora roda em paralelo no core 0 (uploadTask)
}
