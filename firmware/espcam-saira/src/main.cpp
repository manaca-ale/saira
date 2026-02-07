#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "esp_camera.h"
#include "saira_config.h"

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

String getHost(String url) {
  String host = url;
  host.replace("http://", "");
  host.replace("https://", "");
  int pathIndex = host.indexOf("/");
  if (pathIndex != -1) {
    host = host.substring(0, pathIndex);
  }
  return host;
}

void sendStatus(String msg) {
  if(WiFi.status() != WL_CONNECTED) return;

  WiFiClient client;

  String host = getHost(serverBase);
  
  if (client.connect(host.c_str(), 80)) {
    String postData = "message=" + msg;
    client.println("POST /status HTTP/1.1");
    client.println("Host: " + host);
    client.println("Content-Type: application/x-www-form-urlencoded");
    client.println("Content-Length: " + String(postData.length()));
    client.println("Connection: close");
    client.println();
    client.print(postData);
    
    unsigned long timeout = millis();
    while (client.connected() && millis() - timeout < 1000) {
      if (client.available()) {
        String statusLine = client.readStringUntil('\n');
        Serial.print("Status /status -> ");
        Serial.println(statusLine);
        break;
      }
    }
    client.stop();
  }
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

  WiFiClient client;
  String host = getHost(serverBase);

  if (client.connect(host.c_str(), 80)) {
    String head = "--RandomBoundary\r\nContent-Disposition: form-data; name=\"imageFile\"; filename=\"cam.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
    String tail = "\r\n--RandomBoundary--\r\n";
    uint32_t totalLen = fb->len + head.length() + tail.length();

    client.println("POST /upload HTTP/1.1");
    client.println("Host: " + host);
    client.println("Content-Length: " + String(totalLen));
    client.println("Content-Type: multipart/form-data; boundary=RandomBoundary");
    client.println("Connection: close");
    client.println();
    client.print(head);

    uint8_t *fbBuf = fb->buf;
    size_t fbLen = fb->len;
    for (size_t n=0; n<fbLen; n=n+1024) {
      if (n+1024 < fbLen) {
        client.write(fbBuf, 1024);
        fbBuf += 1024;
      } else if (fbLen%1024>0) {
        client.write(fbBuf, fbLen%1024);
      }
    }
    client.print(tail);
    
    // Leitura rápida da resposta para garantir envio
    unsigned long timeout = millis();
    while (client.connected() && millis() - timeout < 5000) {
      if (client.available()) {
        String statusLine = client.readStringUntil('\n');
        Serial.print("Status /upload -> ");
        Serial.println(statusLine);
        break;
      }
    }
    client.stop();
    Serial.println("Foto enviada.");
  } else {
    Serial.println("Erro conexao Ngrok");
  }
  
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
