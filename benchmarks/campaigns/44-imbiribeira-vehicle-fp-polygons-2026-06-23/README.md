# Campaign 44 — Imbiribeira (esp32_001): reduzir FP

Duas alavancas **complementares** para cortar o FP do Imbiribeira (terreno aberto, vista
distante, FP dominado por pedestre passando):

1. **Polígonos recall-safe** (Fase C) — entender onde os descartes reais (TP) caem vs os
   **4 polígonos `pile_zone` atuais** e redesenhá-los para cobrir 100% dos TPs cortando o
   FP que der. Os polígonos gateiam BGSUB (movimento) e o recorte DINOv2.
2. **Gate veículo-focado** (Fase D) — exigir/preferir VEÍCULO no gate e medir o trade-off
   recall × FP.

## Estrutura

```
sql/pull_esp32_001.sql        # COPY read-only das detecções do esp32_001 (prod)
sql/dump_polygons.sql         # dump dos polígonos vivos
data/current_polygons_live.json  # 4 polígonos vivos (esp32_001) — baseline Fase C
scripts/largeN_fetch.py       # baixa frames do S3 (12 even-spaced/evento) -> largeN/
scripts/merge_to_official.py  # mescla no dataset oficial (dedup por event_id)
scripts/build_label_index.py  # gera labeling/index.json (20 TPs) p/ a ferramenta
scripts/polygon_analysis.py   # Fase C: overlay + coverage + proposta recall-safe + SQL
scripts/vehicle_split.py      # Fase D.1: split de veículo dos TPs (bound do recall)
scripts/prompts_vehicle.py    # addons B (veículo hard) e C (veículo soft)
scripts/bench_vehicle_gate.py # Fase D.2: A/B/C recall/spec (Vertex)
tools/tp_marker.html          # (em /tools) marcação manual de TP + veículo
```

## Fase A (FEITO) — pull full-DB + dataset oficial
Pull read-only de prod (`saira-prod` / container `saira-db-prod`) de TODAS as detecções
rotuladas do esp32_001. Resultado: dataset oficial **55 → 211** eventos
(**20 TP / 147 FP / 44 IND**), manifest mestre reconstruído (Mangabeira preservado).

## Fase B — marcação manual dos TPs (VOCÊ)
A ferramenta mostra **todos os frames** de cada TP (1048 frames p/ 20 eventos) — varra até
ver o descarte e marque ali.
```bash
# 1) servir o repo (frames carregam sem CORS)
cd c:\saira && python -m http.server 8009
# 2) abrir no navegador
http://localhost:8009/tools/tp_marker.html
# 3) p/ cada TP:
#    setas ←/→  -> varre os FRAMES (Shift+seta = pula 5) até ver o descarte
#    clique     -> marca o local do descarte (grava em qual frame foi)
#    tecla v    -> veículo presente?  ·  Enter -> próximo TP  ·  p -> anterior  ·  s -> pular
# 4) "Baixar tp_labels.json" -> salvar em labeling/tp_labels.json
```

## Fase C — análise de polígonos
```bash
python scripts/polygon_analysis.py --tp-source manual   # após salvar tp_labels.json
# (preliminar, antes da marcação: --tp-source bbox, aproximado via waste_bbox)
```

## Fase D — split de veículo + benchmark
```bash
python scripts/bench_vehicle_gate.py --workers 6        # A/B/C (Vertex/ADC)
python scripts/vehicle_split.py                         # após bench + tp_labels.json
```

Critério: piso de recall **85%** (peso recall×3 da SAIRA). Ver `report.md`.
