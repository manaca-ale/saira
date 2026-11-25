#!/usr/bin/env bash
# Camp 54, missao 3, rodada 2: cada braco roda o --dry-run (vai para o log) e depois a execucao paga com
# --max-usd. Uso: bash run_round2.sh <log> <braco>:<conjunto>:<max_usd> ...
PY=/c/Saira-migracao/.venv/Scripts/python.exe
log=$1; shift
for spec in "$@"; do
  IFS=: read -r arm set cap <<< "$spec"
  $PY -u run_gate54.py --arm "$arm" --set "$set" --flex --dry-run 2>&1 | grep -v MOCK_MODE | cut -c1-260 >> "$log"
  $PY -u run_gate54.py --arm "$arm" --set "$set" --flex --max-usd "$cap" 2>&1 | grep -v MOCK_MODE | cut -c1-260 >> "$log"
done
