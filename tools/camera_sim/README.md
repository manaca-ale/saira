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
# 3. enviar ao teste por túnel (porta 5002 do servidor = esp32-server de teste)
ssh -N -L 127.0.0.1:15002:127.0.0.1:5002 saira-prod &
python camera_sim.py enviar --eventos eventos_dev.csv --rodada R0 --tag 0 --limite 20 --log r0.jsonl
# 4. rodada do dia inteiro, cada evento na hora do dia original
python camera_sim.py enviar --eventos eventos_dev.csv --rodada R1 --tag 1 --limite 2007 --log r1.jsonl     --hora-original --paralelo 8 --tentativas 6 --retomar
```

A porta local do túnel é a 15002 de propósito: antes de abrir, confira que nada escuta nela
(`netstat -ano | findstr :15002`). Se outro programa já ocupa a porta local, o `ssh` pode
abrir o túnel só no IPv6 e o simulador manda os quadros para o programa errado sem erro
nenhum (aconteceu em 26/11/2026 com a 5002, ocupada por um contêiner local).

`--paralelo`: a amostra `dev` junta 4 meses num dia (33 h de eventos em 24 h); um atrás do
outro a hora do dia atrasaria até 12 h. `--tentativas` repete o lote só quando não há
resposta (túnel caído); `--retomar` pula o que o log já tem como enviado.

Antes de enviar: o dispositivo `pi-cam-sim-001` cadastrado no banco de teste e listado
em `TEST_EVENT_DRIVEN_DEVICES`; `--hora-original` manda cada evento na hora do dia em
que ele aconteceu (o gate recebe `horario_local`), o que espalha a rodada por até 24 h.
