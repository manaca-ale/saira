#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "esp_camera.h"
#include "saira_config.h"
#include "saira_ota.h"

// =============================================================================
// 1. CREDENCIAIS DE REDE (ATUALIZADO)
// =============================================================================
const char* ssid = SAIRA_WIFI_SSID;
const char* password = SAIRA_WIFI_PASSWORD;

// =============================================================================
// 2. CONFIGURAÇÃO DO SERVIDOR (NGROK)
// =============================================================================
// Mantenha seu link do Ngrok atualizado aqui se ele mudar
String serverBase = SAIRA_SERVER_BASE;

// Intervalo de envio (30 segundos)
unsigned long timerDelay = SAIRA_TIMER_DELAY_MS;
unsigned long lastTime = 0;

// Limites de Temperatura
const float MAX_TEMP_LIMIT = 75.0;     
const float RESUME_TEMP_LIMIT = 55.0;  

// =============================================================================
// 3. HARDWARE
// =============================================================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

void configCamera(){
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if(psramFound()){
    config.frame_size = FRAMESIZE_VGA; 
    config.jpeg_quality = 10;          
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Erro Camera init: 0x%x", err);
    delay(3000);
    ESP.restart();
  }

  sensor_t * s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s, 1);
    s->set_contrast(s, 1);
    s->set_saturation(s, 0);  
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);    
    s->set_exposure_ctrl(s, 1);
  }
}


void sendStatus(String msg) {
  if(WiFi.status() != WL_CONNECTED) return;

  String url = sairaJoinPath(serverBase, "/status");
  SairaParsedUrl u = sairaParseHttpUrl(url);
  if (!u.ok) {
    Serial.println("Status: serverBase invalido (precisa http:// ou https://).");
    return;
  }

  WiFiClient plain;
  WiFiClientSecure tls;
  Stream* sock = nullptr;

  if (u.https) {
    if (SAIRA_TLS_INSECURE) tls.setInsecure();
    if (!tls.connect(u.host.c_str(), u.port)) {
      Serial.println("Status: falha conectando TLS.");
      return;
    }
    sock = &tls;
  } else {
    if (!plain.connect(u.host.c_str(), u.port)) {
      Serial.println("Status: falha conectando.");
      return;
    }
    sock = &plain;
  }

  String postData = "message=" + msg;
  sock->println(String("POST ") + u.path + " HTTP/1.1");
  sock->println(String("Host: ") + u.host);
  sock->println("Content-Type: application/x-www-form-urlencoded");
  sock->println(String("Content-Length: ") + String(postData.length()));
  sock->println("Connection: close");
  sock->println();
  sock->print(postData);

  unsigned long timeout = millis();
  while ((u.https ? tls.connected() : plain.connected()) && millis() - timeout < 1000) {
    if (u.https ? tls.available() : plain.available()) {
      String statusLine = u.https ? tls.readStringUntil('
') : plain.readStringUntil('
');
      Serial.print("Status /status -> ");
      Serial.println(statusLine);
      break;
    }
  }

  if (u.https) tls.stop();
  else plain.stop();
}

void sendPhoto() {
  if(WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    return;
  }

  camera_fb_t * fb = esp_camera_fb_get();
  if(!fb) {
    Serial.println("Falha captura frame");
    return;
  }

  String url = sairaJoinPath(serverBase, "/upload");
  SairaParsedUrl u = sairaParseHttpUrl(url);
  if (!u.ok) {
    Serial.println("Upload: serverBase invalido (precisa http:// ou https://).");
    esp_camera_fb_return(fb);
    return;
  }

  WiFiClient plain;
  WiFiClientSecure tls;
  Stream* sock = nullptr;

  if (u.https) {
    if (SAIRA_TLS_INSECURE) tls.setInsecure();
    if (!tls.connect(u.host.c_str(), u.port)) {
      Serial.println("Upload: falha conectando TLS.");
      esp_camera_fb_return(fb);
      return;
    }
    sock = &tls;
  } else {
    if (!plain.connect(u.host.c_str(), u.port)) {
      Serial.println("Upload: falha conectando.");
      esp_camera_fb_return(fb);
      return;
    }
    sock = &plain;
  }

  String head = "--RandomBoundary
Content-Disposition: form-data; name="imageFile"; filename="cam.jpg"
Content-Type: image/jpeg

";
  String tail = "
--RandomBoundary--
";
  uint32_t totalLen = fb->len + head.length() + tail.length();

  sock->println(String("POST ") + u.path + " HTTP/1.1");
  sock->println(String("Host: ") + u.host);
  sock->println(String("Content-Length: ") + String(totalLen));
  sock->println("Content-Type: multipart/form-data; boundary=RandomBoundary");
  sock->println("Connection: close");
  sock->println();
  sock->print(head);

  uint8_t *fbBuf = fb->buf;
  size_t fbLen = fb->len;
  for (size_t n=0; n<fbLen; n=n+1024) {
    if (n+1024 < fbLen) {
      sock->write(fbBuf, 1024);
      fbBuf += 1024;
    } else if (fbLen%1024>0) {
      sock->write(fbBuf, fbLen%1024);
    }
  }
  sock->print(tail);

  unsigned long timeout = millis();
  while ((u.https ? tls.connected() : plain.connected()) && millis() - timeout < 5000) {
    if (u.https ? tls.available() : plain.available()) {
      String statusLine = u.https ? tls.readStringUntil('
') : plain.readStringUntil('
');
      Serial.print("Status /upload -> ");
      Serial.println(statusLine);
      break;
    }
  }

  if (u.https) tls.stop();
  else plain.stop();
  Serial.println("Foto enviada.");

  esp_camera_fb_return(fb);
}

void checkAndManageHeat(bool verbose) {
  float temp = temperatureRead();
  
  // Só imprime se for solicitado (verbose) ou se estiver pegando fogo
  if (verbose) {
    Serial.printf("Status Temp: %.2f C\n", temp);
  }

  if (temp > MAX_TEMP_LIMIT) {
    Serial.printf("!!! SUPERAQUECIMENTO (%.2f C) !!!\n", temp);
    sendStatus("ALERTA CRITICO: Temp " + String(temp) + "C. Pausando.");
    
    while (temp > RESUME_TEMP_LIMIT) {
      delay(5000);
      temp = temperatureRead();
      Serial.printf("Resfriando... %.2f C\n", temp);
    }
    
    sendStatus("INFO: Temp normalizada (" + String(temp) + "C). Retomando.");
  }
}

void setup() {
  Serial.begin(115200);
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); 

  configCamera();

  WiFi.begin(ssid, password);
  Serial.print("Conectando WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Online.");
  sendStatus(String("ESP32 Online ") + ssid);
}

void loop() {
  // Verificação silenciosa de segurança (não imprime nada a menos que dê erro)
  checkAndManageHeat(false);

  // OTA check is cheap (rate-limited) and safe to call frequently.
  sairaMaybeCheckOta();

  if ((millis() - lastTime) > timerDelay) {
    // Agora sim, imprime a temperatura junto com a foto
    Serial.println("\n--- Ciclo de 30s ---");
    checkAndManageHeat(true); // true = imprime a temperatura agora
    
    // Envia um ping leve antes da foto para testar conectividade
    sendStatus("PING: antes da foto");

    sendPhoto();
    lastTime = millis();
  }
}
