# Análise Crítica do Ingester — Automação Android com Dispositivos Físicos

## Resumo

O ingester é um sistema de automação que captura screenshots de câmeras IP via app Android (ICSee) usando ADB em dispositivos físicos. Esta análise avalia o código atual contra as melhores práticas da indústria para automação Android.

---

## 1. Problema Crítico: Coordenadas Hardcoded

**Arquivos afetados:** `config.py`, `capture.py`

O sistema inteiro depende de coordenadas X,Y fixas para navegação:

```python
CAMERAS = {
    "camera_quarto_1": {"tap_coords": {"x": 833, "y": 480}},
    "camera_quarto_2": {"tap_coords": {"x": 250, "y": 480}}
}
PRE_CAPTURE_RITUAL = {"fullscreen_tap": {"x": 540, "y": 960}}
```

**Por que é problemático:**
- Coordenadas quebram se a resolução, DPI ou orientação da tela mudar
- Qualquer atualização do app ICSee que mude o layout invalida toda a configuração
- Trocar de dispositivo exige recalibração manual completa
- É a abordagem mais frágil possível segundo a literatura

**Recomendação:**
Migrar para [uiautomator2](https://github.com/openatx/uiautomator2) (Python wrapper), que permite localizar elementos por `text`, `resourceId`, `className` ou `XPath`. Isso torna os scripts resilientes a mudanças de layout e resolução. Reservar coordenadas apenas para elementos que o uiautomator2 não consegue acessar (canvas, WebView).

```python
# Ao invés de:
adb_adapter.tap(833, 480)

# Usar:
import uiautomator2 as u2
d = u2.connect()
d(text="Camera Quarto 1").click()
```

Se coordenadas forem inevitáveis (app com UI não acessível), ao menos calcular dinamicamente via dump da hierarquia UI ao invés de hardcode.

**Severidade: Alta** — É a maior fonte de fragilidade do sistema.

---

## 2. Sleeps Fixos vs. Waits Dinâmicos

**Arquivos afetados:** `capture.py`, `config.py`

O código usa `time.sleep()` em vários pontos com tempos fixos:

```python
INTER_CAMERA_DELAY = 2.0
STREAM_LOAD_TIMEOUT = 15
BACK_PRESS_DELAY = 1.0
```

**Por que é problemático:**
- Sleeps fixos são a causa #1 de flakiness em automação Android
- Se o dispositivo estiver lento (bateria baixa, pouca RAM), o sleep pode ser insuficiente
- Se estiver rápido, desperdiça tempo desnecessariamente

**O que já está bom:**
- `_wait_for_stream()` já implementa polling — isso é correto

**Recomendação:**
Substituir todos os `time.sleep()` por waits condicionais. O uiautomator2 oferece `d.wait_activity()`, `d(text="X").wait()`, e `wait_timeout` configurável. Para o ADB puro, implementar um helper genérico de polling:

```python
def wait_until(condition_fn, timeout=15, interval=1.0, desc="condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition_fn():
            return True
        time.sleep(interval)
    raise TimeoutError(f"{desc} not met in {timeout}s")
```

**Severidade: Média**

---

## 3. Ausência de Device Management Robusto

**Arquivo afetado:** `adb_adapter.py`

O sistema assume um único dispositivo conectado e não tem lógica robusta de reconexão:

```python
def list_devices():
    # Lista dispositivos mas não gerencia conexão
```

**Problemas:**
- Sem lógica de reconexão automática quando o USB desconecta momentaneamente
- Sem heartbeat de conexão ADB (além do health check periódico)
- `adb kill-server` + `adb start-server` é usado apenas em timeout — deveria ser uma estratégia de recuperação mais ampla
- Sem suporte a múltiplos dispositivos simultâneos

**Recomendação:**
- Implementar um **device watchdog** que verifica a conexão ADB a cada N segundos e tenta reconectar
- Usar `adb -s <serial>` explicitamente em todos os comandos (já parcialmente feito)
- Adicionar retry com backoff exponencial para comandos ADB que falham por desconexão
- Considerar conexão via WiFi ADB (`adb tcpip 5555`) como fallback para USB instável

**Severidade: Média-Alta** — Em produção 24/7, desconexões USB são inevitáveis.

---

## 4. Classificação de Tela por Pixel Analysis — Fragilidade

**Arquivos afetados:** `screen_classifier.py`, `screen_fingerprint.py`

A classificação de estado da tela usa análise de pixels (dark ratios, bright ratios, h-line scores) com thresholds manuais:

```python
SCREEN_STATE_THRESHOLDS = {
    "camera_normal": {"dark_ratio_top_min": 0.5},
    "camera_fullscreen": {"dark_ratio_left_min": 0.7},
    "home": {"h_line_status_bottom_max": 0.3},
}
```

**Por que é problemático:**
- Thresholds calibrados para um dispositivo/resolução específica
- Qualquer mudança de brilho, tema do sistema, wallpaper ou atualização do app invalida os thresholds
- O classificador tem 5 estados mas usa decision tree de 4 regras com fallback para UNKNOWN — pouco discriminativo

**O que já está bom:**
- A abordagem de fingerprinting é criativa e a ferramenta de calibração é útil
- O fallback para UNKNOWN com recovery é uma boa prática

**Recomendação:**
- Usar `dumpsys window` / `dumpsys activity` (já parcialmente usado para focus) como fonte primária de estado — é determinístico
- O uiautomator2 pode fazer `d.app_current()` para saber o app/activity atual e `d.dump_hierarchy()` para o estado completo da UI
- Manter a análise visual apenas como validação secundária (ex: detectar tela preta/congelada)

**Severidade: Média**

---

## 5. Tratamento de Erros — Bom mas Pode Melhorar

**Arquivo afetado:** `capture.py`, `adb_adapter.py`

**O que está bom:**
- Multi-level error handling (comando → step → ciclo)
- Coleta de artefatos em erro (logcat, health, screenshot, window dump)
- Logging estruturado em JSONL
- Retry em screenshots com validação

**O que pode melhorar:**
- Falta um **circuit breaker**: após N falhas consecutivas, o sistema deveria entrar em modo degradado (ex: reiniciar app, reiniciar ADB server, notificar operador)
- Não há **alerting/notificação** — falhas só são detectadas olhando logs
- O error backoff é fixo (30s) — deveria ser exponencial
- Falta categorização de erros (transiente vs. permanente)

**Recomendação:**
```python
class CircuitBreaker:
    def __init__(self, max_failures=5, reset_timeout=300):
        self.failures = 0
        self.max_failures = max_failures
        self.state = "closed"  # closed, open, half-open

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.max_failures:
            self.state = "open"
            # Trigger recovery: restart ADB, reboot device, notify

    def record_success(self):
        self.failures = 0
        self.state = "closed"
```

**Severidade: Média**

---

## 6. Estrutura de Código e Manutenibilidade

### 6.1 Arquivos Vazios
`cameras.py`, `s3.py`, `sqs.py` são placeholders vazios. Remover ou adicionar `raise NotImplementedError` para deixar claro que são pendentes.

### 6.2 Responsabilidades Misturadas em `capture.py`
O arquivo `capture.py` (~665 linhas) acumula:
- Análise de imagem
- Validação de foco
- Classificação de tela
- Orquestração de captura
- Loop infinito
- Logging de ciclos
- Coleta de artefatos de erro

**Recomendação:** Separar em módulos:
- `image_analyzer.py` — análise de pixels, validação de screenshot
- `capture_orchestrator.py` — workflow de captura
- `cycle_runner.py` — loop principal e logging de ciclos

### 6.3 Config Hardcoded
Coordenadas de câmeras, thresholds e activities esperadas estão hardcoded em `config.py`. Considerar migrar para um arquivo externo (YAML/JSON) que pode ser editado sem mexer no código.

### 6.4 Sem Testes Automatizados
Não há testes unitários. `test_classifier.py` é uma ferramenta de diagnóstico manual, não um teste automatizado.

**Recomendação:** Criar testes para:
- Parsing de output ADB (battery, storage, network)
- Classificação de tela com imagens de referência
- Validação de screenshots
- Recovery flows (mockando ADB)

**Severidade: Baixa-Média**

---

## 7. Segurança e Operação 24/7

### 7.1 Sem Watchdog de Processo
Se o processo Python morrer, nada o reinicia automaticamente.

**Recomendação:** Usar systemd (Linux), supervisord, ou Docker restart policy para garantir uptime.

### 7.2 Acúmulo de Artefatos
Screenshots e artefatos de erro se acumulam em disco sem cleanup.

**Recomendação:** Implementar rotação/cleanup automático (ex: manter apenas últimos 7 dias).

### 7.3 Sem Métricas Exportáveis
Health checks salvam em JSONL local mas não expõem métricas para monitoramento externo.

**Recomendação:** Expor métricas via Prometheus endpoint ou enviar para serviço de monitoramento. Pelo menos criar um endpoint HTTP simples de healthcheck.

### 7.4 Temperatura do Dispositivo
O health check coleta temperatura da bateria, mas não age sobre ela.

**Recomendação:** Se temperatura > threshold, pausar captura para evitar throttling e dano ao dispositivo.

**Severidade: Média** (para operação contínua)

---

## 8. Alternativas de Framework

O código atual usa ADB "raw" via subprocess. Alternativas mais robustas:

| Framework | Vantagem | Desvantagem |
|-----------|----------|-------------|
| [uiautomator2](https://github.com/openatx/uiautomator2) | Python nativo, seletores por elemento, rápido | Requer ATX agent no device |
| [Appium](https://appium.io/) | Cross-platform, ampla comunidade | Overhead de servidor, mais complexo |
| [scrcpy](https://github.com/Genymobile/scrcpy) | Stream de tela eficiente, screenshot rápido | Foco em espelhamento, não automação |
| ADB puro (atual) | Zero dependências no device | Frágil, coordenadas fixas, lento |

**Recomendação principal:** Migrar para **uiautomator2** — é a melhor relação custo-benefício para o caso de uso. Mantém Python, adiciona seletores por elemento, waits nativos, e screenshot mais rápido (via minicap).

---

## 9. Resumo de Prioridades

| # | Item | Severidade | Esforço |
|---|------|-----------|---------|
| 1 | Migrar de coordenadas fixas para seletores (uiautomator2) | Alta | Alto |
| 2 | Device watchdog / reconexão automática | Média-Alta | Médio |
| 3 | Substituir sleeps por waits condicionais | Média | Baixo |
| 4 | Circuit breaker + backoff exponencial | Média | Médio |
| 5 | Classificação de tela via dumpsys/hierarchy (não pixels) | Média | Médio |
| 6 | Cleanup de artefatos + monitoramento externo | Média | Baixo |
| 7 | Separar responsabilidades do capture.py | Baixa-Média | Médio |
| 8 | Testes automatizados | Baixa-Média | Médio |
| 9 | Config externo (YAML/JSON) | Baixa | Baixo |

---

## 10. O que Está Bem Feito

- **Health monitoring** abrangente (bateria, storage, rede, memória, uptime)
- **Logging estruturado** com JSONL para ciclos e health — facilita análise posterior
- **Recovery automático** por estado de tela — boa resiliência
- **Validação de screenshots** (foco + análise de imagem) — evita salvar capturas inválidas
- **Feature flags** para habilitar/desabilitar componentes — boa operabilidade
- **Artefatos de debug em erro** — facilita diagnóstico pós-mortem
- **Ferramenta de calibração** do fingerprint — prática para setup inicial

---

## 11. Análise de Artefatos de Erro (Logs de Produção)

Foram analisados 96 diretórios de artefatos (cycle_21 a cycle_548) coletados em 2026-01-30. Cada diretório contém `health.json`, `logcat.txt` e `window.txt`.

### 11.1 Erros Identificados

#### Erro A — Stream Loading Timeout (mais frequente)

**Ciclos afetados:** 500, 501, 502, 546, 547, 548

```
ERROR - [camera_quarto_2] Timeout aguardando stream (15s)
ERROR - Stream nao carregou para camera_quarto_2 dentro de 15s
```

O stream da câmera IP não carrega dentro do timeout de 15 segundos. Afeta ambas as câmeras alternadamente.

**Causa raiz identificada no logcat (ciclo 500):**
- O app ICSee apresentou **ANR (Application Not Responding)** com duração de 3050ms
- Heap de memória em 508MB/512MB (**99% ocupado**)
- Múltiplos bloqueios de GC (Garbage Collector) de até 1.6s cada:
  ```
  WaitForGcToComplete blocked Alloc on Background for 1.684s
  WaitForGcToComplete blocked Alloc on Background for 1.577s
  WaitForGcToComplete blocked Alloc on Background for 1.528s
  ```
- Erro de processamento de stream: `OnMessage ERROR-->没有接收对象 9` ("Sem objeto receptor")

**Conclusão:** O app ICSee está com **memory leak** ou consumo excessivo de memória. Quando o heap fica cheio, o GC bloqueia threads por segundos, impedindo o carregamento do stream a tempo.

**Correções recomendadas:**
1. **Reiniciar o app periodicamente** (ex: a cada 50 ciclos) com `am force-stop com.icsee.pro` seguido de relaunch — isso libera memória acumulada
2. **Aumentar o timeout de stream** de 15s para 25-30s para acomodar GC stalls
3. **Monitorar memória do app** via `dumpsys meminfo com.icsee.pro` e reiniciar automaticamente quando heap > 90%
4. **Adicionar retry do ciclo inteiro** quando stream timeout ocorre, precedido de force-stop do app

---

#### Erro B — Falha ao Entrar em Fullscreen (ciclo 526)

```
ERROR - [camera_quarto_1] Nao entrou em fullscreen apos 3 tentativas
```

Após 3 tentativas do ritual de pré-captura, a tela não transicionou para fullscreen.

**Causa provável:** Com o app sob pressão de memória (ver Erro A), a resposta ao tap é lenta ou ignorada. O tap em coordenadas fixas pode ter errado o alvo se houve micro-lag no rendering.

**Correções recomendadas:**
1. Após falha de fullscreen, fazer `force-stop` + relaunch antes de retry (não apenas repetir o tap)
2. Usar wait condicional ao invés de tentativas cegas — verificar estado da tela entre tentativas com intervalo maior

---

#### Erro C — Cascata de Falhas no Checkpoint A (ciclos 527-533)

```
ERROR - Checkpoint A falhou: nao conseguiu voltar para camera_list (estado=camera_normal)
```

**7 ciclos consecutivos** falharam no mesmo ponto: o sistema não consegue sair do estado `camera_normal` para voltar ao `camera_list`. O recovery tenta `BACK` uma vez (correto para `camera_normal`), mas não funciona.

**Análise:**
- O Erro B (ciclo 526) deixou o app num estado inconsistente
- O BACK press não surtiu efeito — o app provavelmente estava travado/não responsivo (ANR residual)
- O recovery atual tenta no máximo 2 vezes com BACK, mas **não escala para force-stop** quando BACK falha
- Resultado: 7 ciclos (~4 minutos) completamente perdidos até o sistema se recuperar

**Este é o bug mais grave**: o recovery não tem escalação suficiente.

**Correções recomendadas:**
1. **Escalação de recovery**: se BACK não funcionar após 2 tentativas, escalar para `force-stop` + relaunch
2. **Implementar circuit breaker**: após 3 falhas consecutivas no mesmo checkpoint, assumir que o app travou e fazer force-stop incondicional
3. **Adicionar `am force-stop` como arma de recovery** — atualmente o código só usa BACK e HOME, nunca mata o app

---

### 11.2 Timeline dos Erros

| Hora | Ciclo | Erro | Câmera |
|------|-------|------|--------|
| 09:07 | 500 | Stream Timeout | camera_quarto_2 |
| 09:08 | 501 | Stream Timeout | camera_quarto_1 |
| 09:09 | 502 | Stream Timeout | camera_quarto_1 |
| 09:56 | 526 | Fullscreen Falhou | camera_quarto_1 |
| 09:57–10:01 | 527-533 | Checkpoint Cascata (7x) | N/A |
| 10:26 | 546 | Stream Timeout | camera_quarto_2 |
| 10:28 | 547 | Stream Timeout | camera_quarto_1 |
| 10:29 | 548 | Stream Timeout | camera_quarto_1 |

### 11.3 Estado do Dispositivo

| Métrica | Valor |
|---------|-------|
| Dispositivo | Xiaomi MIUI (MTK), Serial 1073e8400412 |
| Bateria | 100% (AC powered) |
| Temperatura | 36.4°C |
| IP WiFi | 192.168.0.15 |
| Internet | OK |
| ADB | Conectado, estável |
| Uptime | ~16 horas |
| RAM disponível | ~655 MB (sistema) |
| Heap do app | 508/512 MB (99% — **crítico**) |

**Conclusão:** O hardware e a conectividade estão saudáveis. Todos os erros são na camada de aplicação (app ICSee com memory leak / GC stalls).

### 11.4 Plano de Ação Baseado nos Erros Reais

| # | Ação | Resolve | Esforço |
|---|------|---------|---------|
| 1 | Reinício periódico do app ICSee (force-stop a cada N ciclos) | Erros A, B, C | Baixo |
| 2 | Escalação de recovery: BACK → HOME → force-stop | Erro C (cascata) | Baixo |
| 3 | Monitorar heap do app e reiniciar quando > 90% | Erro A (preventivo) | Médio |
| 4 | Aumentar stream timeout para 25-30s | Erro A (tolerância) | Trivial |
| 5 | Circuit breaker: 3 falhas consecutivas → force-stop | Erro C | Médio |

---

## Fontes

- [uiautomator2 — Python Wrapper](https://github.com/openatx/uiautomator2)
- [Android UI Automator — Documentação Oficial](https://developer.android.com/training/testing/other-components/ui-automator)
- [BrowserStack — Android App Automation using UIAutomator](https://www.browserstack.com/guide/android-app-automation-using-uiautomator)
- [Appium Common Pitfalls 2025 — Medium](https://medium.com/@abhishek.builds/mobile-automation-with-appium-common-pitfalls-and-how-to-fix-them-2025-guide-aa352228c49a)
- [ADB Cheat Sheet — AutomateThePlanet](https://www.automatetheplanet.com/adb-cheat-sheet/)
- [AWS Device Farm — Troubleshooting](https://docs.aws.amazon.com/devicefarm/latest/developerguide/troubleshooting-android-applications.html)
- [CTG — Android UI Automation Using Python Wrapper](https://www.ctg.com/blogs/android-ui-automation-using-python-wrapper-for-ui-automator)
