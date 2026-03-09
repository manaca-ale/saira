#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "saira_config.h"
#include "saira_runtime_config.h"
#include "saira_wifi.h"

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n\n========================================");
  Serial.println("DIAGNOSTICO DE WIFI SAIRA INICIADO");
  Serial.println("========================================\n");

  SairaRuntimeConfig rt = sairaLoadRuntimeConfig();
  String ssid = rt.wifiSsid.length() ? rt.wifiSsid : String(SAIRA_WIFI_SSID);
  String pass = rt.wifiPassword.length() ? rt.wifiPassword : String(SAIRA_WIFI_PASSWORD);
  String devId = rt.deviceId.length() ? rt.deviceId : "DIAG-TEST";

  Serial.printf("Tentando conectar ao SSID: %s\n", ssid.c_str());
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), pass.c_str());

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(1000);
    attempts++;
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[OK] WiFi Conectado!");
    Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("Gateway: %s\n", WiFi.gatewayIP().toString().c_str());
    Serial.printf("Sinal (RSSI): %d dBm\n", WiFi.RSSI());
  } else {
    Serial.println("\n[ERRO] Falha ao conectar no WiFi.");
  }
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[ALERTA] WiFi desconectado! Tentando reconectar...");
    WiFi.reconnect();
    delay(5000);
    return;
  }

  int rssi = WiFi.RSSI();
  Serial.printf("\n--- Teste de Rede (RSSI: %d dBm) ---\n", rssi);

  // Teste 1: Google (Internet Geral)
  {
    HTTPClient http;
    uint32_t t0 = millis();
    http.begin("http://www.google.com");
    http.setTimeout(5000);
    int code = http.GET();
    uint32_t duration = millis() - t0;
    Serial.printf("Google Ping: %d ms | Codigo: %d\n", duration, code);
    http.end();
  }

  // Teste 2: Seu Servidor (Upload)
  {
    HTTPClient http;
    uint32_t t0 = millis();
    // Usando o servidor do seu config
    String url = String(SAIRA_SERVER_BASE) + "/status";
    http.begin(url);
    http.setTimeout(5000);
    int code = http.GET();
    uint32_t duration = millis() - t0;
    Serial.printf("Seu Servidor: %d ms | Codigo: %d\n", duration, code);
    http.end();
  }

  // Teste de estabilidade de sinal
  if (rssi < -75) {
    Serial.println("[CRITICO] Sinal muito fraco. Isso causa 'Software caused connection abort'.");
  } else if (rssi < -65) {
    Serial.println("[AVISO] Sinal moderado. Pode haver instabilidade em arquivos grandes.");
  } else {
    Serial.println("[OK] Sinal forte.");
  }

  delay(5000); // Testa a cada 5 segundos
}
