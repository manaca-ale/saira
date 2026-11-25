# Simulador da pi-cam

Manda eventos históricos da pi-cam-001 (só o conjunto `dev` da campanha 54) ao
`esp32-server` de **teste**, exatamente como a Pi manda: `POST /upload-batch`, cabeçalho
`X-Device-Id`, lotes de 5 quadros no intervalo original e `event_state=end` no último
lote. Nunca usa o id da câmera real. Detalhes no docstring de `camera_sim.py`.

```bash
# 1. lista dos eventos, com o que o replay previu em cada etapa, e as rodadas R0/R1
python camera_sim.py montar --saida eventos_dev.csv
# 2. conferir sem enviar
python camera_sim.py enviar --eventos eventos_dev.csv --rodada R0 --tag 0 --limite 20 --log r0.jsonl --seco
# 3. enviar ao teste por túnel (porta 5002 = esp32-server de teste)
ssh -N -L 5002:127.0.0.1:5002 saira-prod &
python camera_sim.py enviar --eventos eventos_dev.csv --rodada R0 --tag 0 --limite 20 --log r0.jsonl
```

Antes de enviar: o dispositivo `pi-cam-sim-001` cadastrado no banco de teste e listado
em `TEST_EVENT_DRIVEN_DEVICES`; `--hora-original` manda cada evento na hora do dia em
que ele aconteceu (o gate recebe `horario_local`), o que espalha a rodada por até 24 h.
