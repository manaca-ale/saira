# Runbook de rollout — esp32_002 pós-mudança (campanha 45)

> ⚠️ Executar **em ordem**. Todos os passos são env/DB — **nenhuma mudança de código, nenhum rebuild**.
> Valores `<...>` são preenchidos com o operating point vencedor do sweep (`results/sweep_45.json`).

## Pré-condições

- [ ] Sweep BGSUB concluído com config que perde **0 de 12** detecções confirmadas.
- [ ] A/B do detail concluído (braço vencedor mantém 12/12 CONF).
- [ ] Polígono `proposed` aprovado pelo usuário (`viz/conf_perdidas_pelo_bgsub.png`).

## 0. Rollback — capturar o estado atual ANTES de mudar

```bash
ssh saira-prod "docker exec saira-db-prod psql -U postgres -d saira_db -t -A -c \
  \"SELECT pile_zone_polygon::text, bgsub_persistence_threshold, bgsub_min_persistence_frames, \
     bgsub_min_px_active FROM cameras WHERE device_id='esp32_002';\"" | tee rollback_camera_row.txt
ssh saira-prod "cd /home/ubuntu/saira/services && cp .env .env.bak-camp45-\$(date +%Y%m%d-%H%M)"
```
Valor conhecido em 15/07 (rollback do polígono): `[[[496,322],[554,357],[660,328],[610,298]]]`; os 3 params BGSUB estão **NULL** (usam o env global).

## 1. Geometria + parâmetros por câmera (DB)

Só afeta esp32_002 — as colunas são per-camera (`_resolved_config`, `bgsub_filter.py:125-140`).
⚠️ Manter o aninhamento **lista-de-polígonos** `[[[x,y],...]]`; formato flat faz `get_mask` falhar em silêncio (fail-open de toda a geometria).

```sql
UPDATE cameras SET
  pile_zone_polygon = '[[[474,338],[500,312],[612,290],[692,296],[740,320],[706,348],[592,372],[508,372]]]'::jsonb,
  bgsub_persistence_threshold  = <THR>,
  bgsub_min_persistence_frames = <MF>,
  bgsub_min_px_active          = <MIN_PX>,
  updated_at = NOW()
WHERE device_id = 'esp32_002';
```

## 2. Recalibrar o baseline BGSUB para a cena nova

Só se o sweep apontar o braço `fresh` como vencedor (o npz de prod vem absorvendo a cena nova desde 09/07 via adaptive; o sweep compara os dois).

```bash
ssh saira-prod "docker exec saira-yolo-worker-prod python -m worker.recalibrate_bgsub --device esp32_002 --mix-night"
ssh saira-prod "docker exec saira-yolo-worker-prod tail -2 /app/state/bgsub_models/recalibrate_log.jsonl"   # ok:true + .bak criado
```

## 3. `.env` de prod (`/home/ubuntu/saira/services/.env`)

⚠️ Este `.env` é **compartilhado test↔prod** — as flags valem para test no próximo redeploy.

```diff
- GEMINI_DETAIL_PILECROP_ENABLED=false
+ GEMINI_DETAIL_PILECROP_ENABLED=true      # reativa pilecrops + prompt HIGHBAR (DETAIL_HIGHBAR_DEVICES=esp32_002 já setado)
                                            # restrito a esp32_002 por DETAIL_PILECROP_DEVICES (default do compose)
- BGSUB_SHADOW_DEVICES=esp32_002
+ BGSUB_SHADOW_DEVICES=                    # BGSUB volta a BLOQUEAR (esp32_002 era o único da lista)
```

`STRUCTURAL_FILTER_MODE` e `STRUCTURAL_RECOVERY_MODE` **continuam `off`** — structural-delta foi reprovado nesta cena (AUC 0,827 → 0,46; ver `report.md` §5.1).

## 4. Recriar o worker

`docker compose restart` **não** relê o `.env`; e a máscara do BGSUB é cacheada por device (`get_mask`) → o restart também é obrigatório para o polígono novo valer.

```bash
ssh saira-prod "cd /home/ubuntu/saira/services && docker compose -p saira-prod -f docker-compose.prod.yml up -d --no-deps yolo-worker"
```

## 5. Verificação (15 min depois)

```bash
# máscara nova (bbox deve refletir o polígono proposto, não 496..660)
ssh saira-prod "docker logs saira-yolo-worker-prod --since 20m 2>&1 | grep 'built zone mask for esp32_002'"
# BGSUB bloqueando de verdade (shadow:false no ledger)
ssh saira-prod "docker exec saira-yolo-worker-prod sh -c \"grep esp32_002 /app/state/bgsub_models/shadow_decisions.jsonl | tail -3\""
# pilecrops ativos
ssh saira-prod "docker logs saira-yolo-worker-prod --since 20m 2>&1 | grep -i pilecrop | head"
# env aplicado
ssh saira-prod "docker exec saira-yolo-worker-prod env | grep -E 'BGSUB_SHADOW_DEVICES|DETAIL_PILECROP_ENABLED|STRUCTURAL_FILTER_MODE'"
```

## 6. Rollback (1 linha por alavanca)

| Alavanca | Reverter |
|---|---|
| BGSUB enforce | `BGSUB_SHADOW_DEVICES=esp32_002` + recriar worker |
| pilecrops/HIGHBAR | `GEMINI_DETAIL_PILECROP_ENABLED=false` + recriar worker |
| Params por câmera | `UPDATE cameras SET bgsub_persistence_threshold=NULL, bgsub_min_persistence_frames=NULL, bgsub_min_px_active=NULL WHERE device_id='esp32_002';` (sem restart) |
| Polígono | `UPDATE cameras SET pile_zone_polygon='[[[496,322],[554,357],[660,328],[610,298]]]'::jsonb WHERE device_id='esp32_002';` + recriar worker |
| Baseline npz | `docker exec saira-yolo-worker-prod cp /app/state/bgsub_models/esp32_002.npz.bak /app/state/bgsub_models/esp32_002.npz` (hot-reload por mtime) |

## 7. Monitoramento (5–7 dias)

```sql
-- taxa de confirmação diária vs baseline 9,6%
SELECT (created_at AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       count(*) FILTER (WHERE status='CONFIRMADO') conf,
       count(*) FILTER (WHERE status='REJEITADO')  rej,
       count(*) FILTER (WHERE status='PENDENTE')   pend
FROM detections WHERE camera_id=11 AND created_at >= TIMESTAMP '<data do rollout>' AT TIME ZONE 'America/Sao_Paulo'
GROUP BY 1 ORDER BY 1;
```

Telemetria de supressão continua existindo em enforce (o ledger grava TODA avaliação):

```bash
# distribuição de persistence + near-miss (massa entre thr e 2×thr = perigo de perder real)
ssh saira-prod "docker exec saira-yolo-worker-prod sh -c \"grep esp32_002 /app/state/bgsub_models/shadow_decisions.jsonl | tail -500\"" > ledger_hoje.jsonl
python scripts/ledger_crosscheck.py
```

**Regra de decisão (fim da semana):** manter se chamadas de gate ≲150/dia, detecções 8–15/dia, confirmação ≥20% (alvo 28%) e 0 descarte real suprimido na auditoria pontual (~10 janelas suprimidas revistas no meio da semana; os frames continuam no arquivo de 5s). Qualquer descarte real suprimido → BGSUB volta a shadow e re-tuna o threshold pela distribuição do ledger.
