#!/usr/bin/env bash
# Junta, do ambiente de TESTE (só leitura), o que o comparar.py precisa.
# Uso: coletar.sh <pasta_de_coleta> <log_do_envio.jsonl> [device_id]
set -euo pipefail
# Comando que roda no servidor e empacota os manifestos dos eventos simulados (sem os
# .lock e .processed, e também os que o worker já moveu para events/arquivo/AAAAMM/).
# O `find` escolhe os arquivos: `tar c --wildcards 'sim*.json'` não expande nada na
# criação e a coleta vinha vazia sem erro (R0 de 26/11/2026).
manifests_cmd() {
  printf '%s' "cd '$1' 2>/dev/null && find . -name 'sim*.json' -print0 | tar cf - --null -T - --transform='s|.*/||' || tar cf - -T /dev/null"
}
if [ "${1:-}" = "--cmd-manifestos" ]; then manifests_cmd "$2"; exit 0; fi
OUT=$1; LOG=$2; DEV=${3:-pi-cam-sim-001}
mkdir -p "$OUT/manifestos" "$OUT/cascade_audit" "$OUT/prefilter_audit"
cp "$LOG" "$OUT/envios.jsonl"
ssh saira-prod "$(manifests_cmd "/home/ubuntu/saira-test/esp32-server/uploads/$DEV/events")" \
  | tar xf - -C "$OUT/manifestos"
ssh saira-prod "docker exec saira-yolo-worker-test sh -c 'cd /app/state && tar cf - gemini_cascade_audit/*/$DEV.jsonl gate_prefilter_audit/*/$DEV.jsonl 2>/dev/null || true'" \
  | tar xf - -C "$OUT"
for d in "$OUT"/gemini_cascade_audit/*/; do [ -d "$d" ] && cp "$d/$DEV.jsonl" "$OUT/cascade_audit/$(basename "$d").jsonl"; done
for d in "$OUT"/gate_prefilter_audit/*/; do [ -d "$d" ] && cp "$d/$DEV.jsonl" "$OUT/prefilter_audit/$(basename "$d").jsonl"; done
ssh saira-prod "docker exec saira-db-test psql -U postgres -d saira_db -c \"BEGIN READ ONLY; COPY (SELECT called_at, agent, model, request_id, input_tokens, output_tokens, estimated_cost_usd, latency_ms, success, error_message FROM gemini_call_log WHERE device_id = '$DEV' ORDER BY called_at) TO STDOUT WITH CSV HEADER; ROLLBACK;\"" \
  | grep -vE '^(BEGIN|ROLLBACK)$' > "$OUT/gemini_call_log.csv"
echo "coleta em $OUT: $(ls "$OUT/manifestos" | wc -l) manifestos, $(cat "$OUT"/cascade_audit/*.jsonl 2>/dev/null | wc -l) janelas no gate, $(cat "$OUT"/prefilter_audit/*.jsonl 2>/dev/null | wc -l) no filtro, $(($(wc -l < "$OUT/gemini_call_log.csv") - 1)) chamadas"
