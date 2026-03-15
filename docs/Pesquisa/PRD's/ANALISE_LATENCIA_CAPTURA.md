# Analise de Latencia na Captura — IP Camera via ESP32

## O Problema

O ciclo de captura da camera IP leva tempo significativo porque o ESP32 precisa:

1. **Abrir conexao TCP** com a camera (handshake)
2. **Autenticar** (Basic ou Digest — Digest requer 2 round-trips)
3. **Baixar o JPEG** (~224 KB) pela rede WiFi local
4. **Fechar conexao**

Cada captura repete todo esse ciclo do zero. A fila PSRAM desacopla captura de upload, mas nao resolve o gargalo fundamental: **o download do snapshot e lento**.

A autenticacao Digest e especialmente custosa — sao 3 requests HTTP por captura:

```
[1] GET /snap.jpg         -> 401 (busca WWW-Authenticate)
[2] GET /snap.jpg          -> 401 (challenge do nonce)
[3] GET /snap.jpg + Auth   -> 200 + JPEG
```

---

## Solucoes de Software

### 1. Manter conexao HTTP persistente (Keep-Alive)

**Impacto: ALTO | Esforco: MEDIO**

Hoje o codigo cria um `HTTPClient` novo a cada captura e chama `http.end()` ao final. Manter a conexao TCP aberta entre capturas elimina o overhead de handshake + autenticacao repetida.

**Como implementar:**
- Mover o `HTTPClient` e o `WiFiClient` para variaveis globais/static
- Adicionar header `Connection: keep-alive`
- Nao chamar `http.end()` entre capturas; reutilizar a conexao
- Tratar reconexao apenas quando a conexao cair
- Reautenticar com Digest apenas quando o nonce expirar (HTTP 401)

**Ganho estimado:** Elimina ~200-500ms por captura (handshake TCP + auth)

**Risco:** Algumas cameras IP baratas fecham a conexao apos cada request. Precisa de fallback para reconexao.

---

### 2. Cache do Digest nonce (evitar 2 round-trips)

**Impacto: ALTO | Esforco: PEQUENO**

O codigo atual faz 3 requests para autenticacao Digest a cada captura. O nonce do Digest pode ser reutilizado (incrementando o nonce count `nc`).

**Como implementar:**
- Salvar `nonce`, `realm`, `qop`, `opaque` da ultima resposta 401
- Nas capturas seguintes, enviar Authorization direto com `nc` incrementado
- Somente refazer o challenge completo se receber 401 (nonce expirado)

**Ganho estimado:** Reduz de 3 para 1 request HTTP por captura (quando Digest ativo)

**Risco:** Nenhum — e o comportamento padrao do RFC 7616.

---

### 3. Usar endpoint de menor resolucao da camera

**Impacto: ALTO | Esforco: MINIMO**

Muitas cameras IP oferecem multiplos endpoints com resolucoes diferentes. O `ipcam_snapshot_discover.py` ja identifica a menor opcao disponivel.

Exemplos comuns (Hikvision, Dahua, cameras genericas):

| Endpoint                              | Resolucao tipica | Tamanho |
|---------------------------------------|-----------------|---------|
| `/snap.jpg`                           | Maximo          | ~224 KB |
| `/cgi-bin/snapshot.cgi?channel=1&subtype=1` | Sub-stream | ~30-60 KB |
| `/snap.jpg?w=640&h=480`              | VGA             | ~40-80 KB |
| `/snap.jpg?size=3`                   | QVGA            | ~15-30 KB |

**Como implementar:**
- Rodar `ipcam_snapshot_discover.py` para encontrar o menor endpoint
- Atualizar `SAIRA_IP_CAM_URL` no `.env` para usar o endpoint menor
- Ou usar remote config para ajustar `ip_cam_url` dinamicamente

**Ganho estimado:** Reduz download de ~224 KB para ~40-80 KB (2-5x mais rapido)

**Risco:** Menor resolucao pode afetar a qualidade da deteccao YOLO. Para o fake worker nao importa; para YOLO real, testar qual resolucao minima mantem accuracy aceitavel.

---

### 4. MJPEG stream em vez de snapshots individuais

**Impacto: MUITO ALTO | Esforco: ALTO**

Em vez de fazer requests HTTP individuais para cada snapshot, abrir um stream MJPEG continuo e extrair frames.

A maioria das cameras IP oferece endpoint MJPEG:
- `/video.mjpeg`
- `/cgi-bin/mjpeg.cgi`
- `/stream?channel=1`

**Como implementar:**
- Abrir uma unica conexao HTTP para o endpoint MJPEG
- Parsear o boundary do multipart (`--BoundaryString`)
- Extrair frames JPEG individuais do stream
- Enfileirar na PSRAM queue como hoje

**Ganho estimado:** Elimina completamente o overhead de conexao/auth. Latencia entre frames cai para o que a camera consegue produzir (~33ms a 30fps).

**Risco:**
- Implementacao mais complexa (parser de multipart stream)
- Consome banda continua (mesmo quando nao precisa de frame)
- Precisa de logica para "pular frames" (capturar apenas a cada N segundos)

---

### 5. Aumentar buffer de leitura TCP

**Impacto: MEDIO | Esforco: MINIMO**

O loop de download atual le em chunks pequenos (conforme `stream->available()`). Configurar buffer maior no WiFiClient acelera a transferencia.

**Como implementar:**
```cpp
WiFiClient* stream = http.getStreamPtr();
stream->setNoDelay(true);
// ESP32 Arduino: buffer de recepcao padrao e 1460 bytes
// Pode ser aumentado via menuconfig ou chamando setBufferSizes
```

- Tambem considerar `TCP_WND` no sdkconfig para aumentar janela TCP

**Ganho estimado:** 10-30% mais rapido no download

**Risco:** Usa mais RAM, mas com PSRAM disponivel nao e problema.

---

### 6. Dual-core: captura e upload em paralelo (FreeRTOS tasks)

**Impacto: ALTO | Esforco: ALTO**

O ESP32-S3 tem 2 cores. Hoje tudo roda no loop() de um core. Separar em duas tasks FreeRTOS permite captura e upload verdadeiramente simultaneos.

**Como implementar:**
```
Core 0: Task de captura (download da camera -> push na fila)
Core 1: Task de upload (pop da fila -> POST para servidor)
```

- Usar `xTaskCreatePinnedToCore()` para fixar cada task em um core
- A fila PSRAM ja existe; adicionar mutex/semaforo para acesso thread-safe
- Ou usar `xQueueCreate()` do FreeRTOS em vez da fila manual

**Ganho estimado:** Upload e captura acontecem ao mesmo tempo. Se cada um leva 5s, o ciclo total cai de 10s para ~5s.

**Risco:**
- Complexidade de concorrencia (mutex na fila, WiFi stack thread-safe)
- WiFi no ESP32 ja usa o core 0 internamente — pode haver contencao
- Debug mais dificil

---

### 7. Compressao JPEG na camera (reduzir qualidade)

**Impacto: MEDIO | Esforco: MINIMO**

Configurar a camera IP para usar compressao JPEG mais agressiva reduz o tamanho sem mudar resolucao.

**Como implementar:**
- Acessar interface web da camera
- Reduzir qualidade JPEG para 60-70% (muitas cameras permitem via CGI)
- Exemplo: `/snap.jpg?quality=60`

**Ganho estimado:** Reduz ~224 KB para ~100-150 KB

**Risco:** Artefatos de compressao podem afetar YOLO. Testar com diferentes niveis.

---

## Recomendacao de Prioridade

| # | Solucao | Impacto | Esforco | Prioridade |
|---|---------|---------|---------|------------|
| 3 | Endpoint menor resolucao | Alto | Minimo | **1 - Fazer agora** |
| 2 | Cache do Digest nonce | Alto | Pequeno | **2 - Fazer agora** |
| 7 | Reduzir qualidade JPEG | Medio | Minimo | **3 - Fazer agora** |
| 1 | HTTP Keep-Alive | Alto | Medio | **4 - Proximo sprint** |
| 5 | Buffer TCP maior | Medio | Minimo | **5 - Proximo sprint** |
| 4 | MJPEG stream | Muito Alto | Alto | **6 - Futuro** |
| 6 | Dual-core FreeRTOS | Alto | Alto | **7 - Futuro** |

As solucoes 3, 2 e 7 podem ser implementadas em menos de 1 hora e combinadas provavelmente reduzem o tempo de captura de ~5s para ~1-2s.
