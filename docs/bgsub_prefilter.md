# BGSUB Pre-Filter — pré-filtro OpenCV antes do Gemini gate

**Status:** implementado em `feature/bgsub-prefilter` (2026-05-23). Default OFF.
Habilitar via env `BGSUB_PREFILTER_ENABLED=true` no worker.

## O que faz

Antes de cada chamada ao Gemini gate (Agent-1), o worker aplica um pré-filtro
determinístico de OpenCV (`cv2.BackgroundSubtractorMOG2`) à janela de frames.
Se a janela é "vazia" (sem mudança visual significativa na zona da pilha), o
worker **pula a chamada Gemini** e a janela é tratada como "não-ocorrência".

Validado no dataset oficial v1 (174 janelas, threshold persistence ≥ 1000 px):

- ✅ **100% TP preservados** (14/14) — zero descartes reais perdidos
- ✅ **75% baseline suprimidos** (45/60) — cenas vazias não geram chamada Gemini
- ⚪ FPs de trânsito e poda não são afetados (continuam indo para o Gemini decidir)

**Ganhos esperados em produção** (câmera 24/7, ~720 janelas/dia):

- ~-60% chamadas Gemini gate (cenas vazias dominam)
- ~-73% alarmes falsos de baseline no painel (suprime antes do gate decidir)
- Zero perda de recall

## Arquitetura

```
worker/main.py — _process_with_gemini_cascade_window
   │
   ├─ Constrói janela de N frames
   │
   ├─ if BGSUB_PREFILTER_ENABLED and camera.pile_zone_polygon is not None:
   │      result = bgsub_filter.evaluate(...)
   │      if result.should_suppress:
   │          return (False, {"skipped": True, "skip_reason": "bgsub_filtered"})
   │
   └─ analyze_new_litter_with_gemini(...)   # fluxo normal
```

Failsafes (todos pulam o filtro, segue fluxo normal):

- `BGSUB_PREFILTER_ENABLED=false`
- `camera.pile_zone_polygon` é NULL ou inválido
- Modelo MOG2 não existe em disco para o device
- Qualquer exceção em `evaluate()`

## Configurar uma câmera nova

### 1. Definir polígono da zona da pilha

O polígono delimita a região do frame onde **descartes podem aparecer** (chão
próximo à pilha pré-existente). Pixels fora dessa região são ignorados pelo
filtro — então trânsito de via/calçada longe da pilha não interfere.

Formato JSONB: **lista de polígonos**, cada polígono = **lista de pontos `[x, y]`**.
Frame de referência: **1280×720** (o worker reajusta a máscara automaticamente
se o frame da câmera tiver resolução diferente).

**Imbiribeira (esp32_001) — terreno baldio, poste central:**

```sql
UPDATE cameras SET pile_zone_polygon = '[
  [[40,280],[560,280],[560,720],[40,720]],
  [[800,280],[1240,280],[1240,720],[800,720]]
]'::jsonb
WHERE device_id = 'esp32_001';
```

**Mangabeira (esp32_002) — esquina com lixeira:**

```sql
UPDATE cameras SET pile_zone_polygon = '[
  [[480,60],[920,60],[920,340],[480,340]]
]'::jsonb
WHERE device_id = 'esp32_002';
```

**Via API** (com o endpoint PATCH existente em `/api/v1/cameras/{id}`):

```bash
curl -X PATCH http://localhost:8001/api/v1/cameras/123 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pile_zone_polygon": [[[40,280],[560,280],[560,720],[40,720]]]}'
```

### 2. Calibrar o modelo MOG2 para esta câmera

O modelo de fundo é treinado uma vez a partir de N frames "vazios" (sem
ocorrência). Em prod, esses frames vêm do baseline diário capturado pela
própria câmera (geralmente 1-2 horas em horário sem movimentação).

```bash
# Dentro do container do worker:
python -m scripts.calibrate_bgsub \
    --device-id esp32_001 \
    --frames-dir /app/data/baseline/cam_imbiribeira/day \
    --mix-night /app/data/baseline/cam_imbiribeira/night \
    --n-frames 80 \
    --force
```

Saída: `$STATE_DIR/bgsub_models/esp32_001.npz` (~140 MB para 80 frames 1280×720).

A coluna `bgsub_calibrated_at` é atualizada manualmente após a calibração — o
script imprime o SQL no final.

### 3. Ligar o pré-filtro

No `docker-compose.yml` (ou env override do worker):

```yaml
yolo-worker:
  environment:
    BGSUB_PREFILTER_ENABLED: "true"
    # opcionais (defaults validados):
    # BGSUB_PERSISTENCE_THRESHOLD: "1000"
    # BGSUB_MIN_PX_ACTIVE: "800"
    # BGSUB_MIN_PERSISTENCE_FRAMES: "0.6"
```

Reiniciar o worker:

```bash
docker compose --profile worker restart yolo-worker
```

## Como monitorar

### Métrica Prometheus

`saira_bgsub_eval_total{camera_id, reason}` — contador de avaliações.

`reason` values:

- `filtered` — suprimido (persistence < threshold). Win.
- `passed` — não suprimido, chamada Gemini ocorreu normal.
- `skipped_no_polygon` — câmera sem polígono configurado.
- `skipped_no_model` — modelo MOG2 não encontrado em disco.
- `skipped_disabled` — env var off.
- `error` — exceção no filtro (fail-open).

### Painel Grafana (a adicionar)

```promql
# Taxa de filtragem por câmera
rate(saira_bgsub_eval_total{reason="filtered"}[5m])
  / ignoring(reason) group_left
  sum without (reason) (rate(saira_bgsub_eval_total[5m]))
```

Esperado: 0.4-0.7 (40-70% das janelas filtradas) em câmera típica 24/7.

### Logs estruturados

Quando uma janela é suprimida:

```json
{
  "event": "bgsub_suppressed",
  "device_id": "esp32_001",
  "camera_id": 12,
  "gate_request_id": "uuid",
  "persistence": 247,
  "n_frames_ok": 1,
  "n_frames_total": 5,
  "threshold": 1000
}
```

## Troubleshooting

### "Por que essa janela X foi filtrada?"

1. Pegar o `gate_request_id` do log.
2. Olhar os 5 frames usados pelo worker (`/app/uploads/{device}/`).
3. Rodar manualmente:

```python
from worker import bgsub_filter
result = bgsub_filter.evaluate(
    frame_paths=[Path("frame_001.jpg"), ...],
    device_id="esp32_001",
    pile_zone_polygon=[[[40,280],[560,280],...]],
)
print(result)  # FilterResult(should_suppress=..., reason=..., persistence=...)
```

Se `persistence` está em ~100-500 (próximo ao threshold), considerar ajustar
`BGSUB_PERSISTENCE_THRESHOLD` ou recalibrar o modelo (`scripts/calibrate_bgsub.py`).

### "Calibração está pegando uma janela com atividade"

Ver os 80 frames usados pelo script de calibração antes de rodar. Se algum
contém pessoa ou veículo parado, o MOG2 vai "aprender" esse padrão como
fundo e perder sensibilidade. Use horário 03:00-05:00 da manhã (madrugada
sem movimento) para baseline limpo.

### "TPs estão sendo suprimidos"

Improvável com threshold padrão (validado no spike com 100% TP keep). Se
acontecer:

1. Ver `persistence` reportado no log do TP suprimido.
2. Comparar com a distribuição em `tools/spike_bgsub_output/scores.csv`.
3. Reduzir `BGSUB_PERSISTENCE_THRESHOLD` para `500` (recupera mais, mas
   filtra menos baseline também).

### "Polígono está cortando descartes reais"

Inspecionar visualmente o polígono sobre 1 frame da câmera:

```python
import cv2, numpy as np
img = cv2.imread("frame.jpg")
poly = np.array([[40,280],[560,280],[560,720],[40,720]], dtype=np.int32)
cv2.polylines(img, [poly], True, (0,255,0), 3)
cv2.imwrite("debug_polygon.jpg", img)
```

Ajustar via SQL/PATCH conforme necessário. O polígono é hot-reload — basta
limpar o cache do filtro chamando `bgsub_filter.invalidate_cache(device_id)`
ou reiniciar o worker.

## Limitações conhecidas

- **Não distingue trânsito de descarte** (ambos têm pessoa próxima da pilha).
  Trânsito vai virar 31 FPs que o Gemini ainda precisa rejeitar.
- **Não distingue coleta de descarte** (ambos têm atividade na pilha). Esses
  são edge cases tratados separadamente (V3 prompt) ou via revisão humana.
- **Modelo MOG2 precisa recalibração periódica** quando há mudança visual
  permanente na cena (pilha cresce, vegetação muda). Sintoma: `persistence`
  começa alto mesmo em cena vazia → mais baseline FPs no painel. Solução:
  rodar `calibrate_bgsub` de novo com frames recentes.
- **Polígonos são definidos manualmente** (sem UI no frontend ainda). Próxima
  fase: componente React com canvas para desenhar.

## Bibliografia

- Spike inicial: [tools/spike_bgsub_filter.py](../tools/spike_bgsub_filter.py)
- Bench de validação: [tools/bgsub_bench_replay.py](../tools/bgsub_bench_replay.py)
- Plano original: [C:\Users\aleco\.claude\plans\mighty-pondering-yeti.md](../../Users/aleco/.claude/plans/mighty-pondering-yeti.md)
- Dataset oficial v1: [data/datasets/official/README.md](../data/datasets/official/README.md)
