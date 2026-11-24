# Servidor SAÍRA: o que fazer antes de religar as câmeras (janeiro de 2027)

Roteiro de operação do servidor único `saira-prod` (EC2 `i-092cb60f61bd503e3`, `t3.xlarge`, us-east-1). Medido em 24/11/2026 só com leitura. Cada passo diz o que conferir antes, o comando, como desfazer e o espaço ou o risco. **Nada aqui foi executado.** Siga a ordem: os primeiros passos fecham riscos que existem hoje.

Convenções:
- `M=/var/lib/docker/volumes/saira-prod_esp32_uploads_prod/_data` (volume de uploads da produção).
- `P=/home/ubuntu/saira` (checkout da produção) e `T=/home/ubuntu/saira-test` (checkout do teste, criado no passo 4).
- Antes de cada bloco, `df -h /` para comparar depois.

## Resumo e ordem

| # | Passo | Ganho | Risco | Tempo |
|---|---|---|---|---|
| 1 | Fechar o `esp32-dashboard` (uploads públicos sem senha) | segurança | nenhum para a produção | 5 min |
| 2 | Criar `SECRET_KEY` e `TEST_SECRET_KEY` | segurança (JWT forjável hoje) | todos fazem login de novo | 10 min |
| 3 | Limpeza do disco | ~50 GB (de 87 para ~35 GB) | baixo, passo a passo | 40 min |
| 4 | Separar o checkout do teste | teste não mexe na produção | teste fica fora do ar ~5 min | 20 min |
| 5 | `.env.bak*` para o repositório Envs e apagar | segurança | nenhum | 15 min |
| 6 | Merge do PR de infraestrutura e deploy | portas internas fechadas, log com teto | recria os containers | 15 min |
| 7 | Trocar as senhas padrão (Postgres, Grafana, pgAdmin) | segurança | queda curta se errar a ordem | 20 min |
| 8 | Variáveis do worker para as Pi (`POLL_INTERVAL`, câmera inativa) | latência e disco | baixo | 5 min |
| 9 | IAM Role no lugar das chaves estáticas | segurança | S3/Bedrock param se a política faltar | 30 min |
| 10 | Flags e crons residuais | CPU e ruído | baixo | 15 min |
| 11 | Revisar o Security Group | segurança | câmera ESP32 perde acesso (esperado) | 15 min |
| 12 | Expansão do EBS | só se precisar | baixo | 15 min |

---

## 1. Fechar os uploads públicos (`esp32-dashboard`) — fazer já

**Achado:** o container `esp32-dashboard` (de 15/04/2026, imagem do esp32-server de produção, projeto `saira-prod`) monta o volume de uploads de produção e o cloudflared publica ele em `dashtestesaira.manaca.tech` (porta 5003). Em 24/11 `GET https://dashtestesaira.manaca.tech/uploads/server-events.jsonl` devolveu 200 e 161 MB sem senha, e `/dashboard` e `/api/dashboard/*` também respondem. Os quadros das câmeras (pessoas na rua) e o log de eventos estão baixáveis por quem souber o caminho.

Conferir antes:
```bash
docker inspect -f '{{.Name}} {{.Config.Image}} {{.State.StartedAt}}' esp32-dashboard
grep -n -A1 dashtestesaira /etc/cloudflared/config.yml
```

Fazer:
```bash
docker stop esp32-dashboard            # para de servir na hora
sudo cp -p /etc/cloudflared/config.yml /etc/cloudflared/config.yml.bak.$(date +%Y%m%d)
sudo sed -i '/dashtestesaira.manaca.tech/,+1d' /etc/cloudflared/config.yml   # apaga hostname + service
sudo grep -n "hostname\|service" /etc/cloudflared/config.yml                  # conferir: sobram 4 hostnames + 404
sudo systemctl restart cloudflared
curl -s -o /dev/null -w '%{http_code}\n' https://dashtestesaira.manaca.tech/dashboard   # esperado: 404 ou erro do Cloudflare
docker rm esp32-dashboard              # depois de uma semana sem falta
```
Tirar também o registro DNS `dashtestesaira` no painel do Cloudflare.

Desfazer: `docker start esp32-dashboard`; `sudo cp -p /etc/cloudflared/config.yml.bak.AAAAMMDD /etc/cloudflared/config.yml && sudo systemctl restart cloudflared`.

Fica em aberto (frente `saira-seguranca-apis`): a rota `GET /uploads/...` do esp32-server de produção também é pública na porta 5005 (aberta no Security Group) e via `saira.manaca.tech/uploads/` (o painel usa para as miniaturas). O passo 11 fecha a porta 5005; a rota pelo painel pede autenticação no código.

## 2. Chave dos tokens de login (`SECRET_KEY`) — fazer já

**Achado:** `SECRET_KEY` não existe no `.env`, então o backend de produção e o de teste assinam os JWT com o padrão escrito no compose (`your-secret-key-change-in-production-min-32-chars`), que está no GitHub. Quem leu o repositório forja um token de qualquer usuário em `api-saira.manaca.tech`. O PR deste roteiro torna a variável obrigatória.

Fazer (o `.env` ainda é único neste ponto):
```bash
cd /home/ubuntu/saira/services
cp -p .env .env.bak-secretkey-$(date +%Y%m%d)
grep -c '^SECRET_KEY=\|^TEST_SECRET_KEY=' .env      # esperado: 0
printf 'SECRET_KEY=%s\nTEST_SECRET_KEY=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" >> .env
grep -c '^SECRET_KEY=\|^TEST_SECRET_KEY=' .env      # esperado: 2
```
Aplicar sem esperar o PR (o compose atual já lê `SECRET_KEY`):
```bash
docker compose -p saira-prod --profile worker -f docker-compose.prod.yml up -d --no-deps backend
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' saira-backend-prod | grep -c '^SECRET_KEY=your-secret'   # esperado: 0
```
O teste pega a dele no deploy depois do merge (passo 6). Efeito: todos os usuários precisam entrar de novo. Desfazer: tirar as duas linhas e recriar o backend (volta ao padrão público; não recomendado).

## 3. Limpeza do disco (87 de 96 GB → ~35 GB)

Causa principal: as seis câmeras estão inativas no banco desde 28/09, o worker ignora câmera inativa, mas o esp32-server continuou recebendo; a `esp32_002` deixou 14 GB de quadros brutos entre 01 e 11/10 que nada processa nem limpa. O PR corrige para frente (passo 8); o acumulado sai aqui.

### 3.1 Quadros e vídeos antigos do volume de uploads (~27,8 GB)

| Pasta em `$M` | Tamanho | O que é |
|---|---:|---|
| `esp32_002/2026` | 14 GB | quadros brutos de set/out, nunca processados |
| `videos/pi-cam-001` | 5,8 GB | 21 clipes da Pi de 28/07 a 04/09 |
| `esp32_005/2026` | 3,1 GB | quadros brutos de set a nov |
| `_archive_backlog_20260609` | 2,8 GB | arquivo manual de junho |
| `bulk` | 1,5 GB | uploads em lote de jul a set |

Conferir antes (nenhuma detecção aponta para estas pastas):
```bash
sudo du -sh $M/esp32_002/2026 $M/esp32_005/2026 $M/videos $M/_archive_backlog_20260609 $M/bulk
docker exec saira-db-prod psql -U postgres -d saira_db -Atc "SELECT count(*) FROM detections WHERE image_url ~ '/(esp32_002|esp32_005)/20[0-9]{2}/|/videos/|/bulk/|_archive_backlog'"   # esperado: 0
```

Opção A (recomendada): arquivar no S3 Deep Archive e depois apagar. Custa menos de US$ 1 no total (transferência us-east-1 → sa-east-1 a ~US$ 0,02/GB e ~US$ 0,002/GB/mês de guarda, mínimo de 180 dias). O `tar` vai direto para o S3, sem ocupar disco:
```bash
for d in esp32_002/2026 esp32_005/2026 videos _archive_backlog_20260609 bulk; do
  k=$(echo $d | tr '/' '_')
  sudo tar -C $M -cf - $d | aws s3 cp - s3://saira-images/arquivo-servidor-2026/$k.tar \
    --storage-class DEEP_ARCHIVE --expected-size 16000000000 --region sa-east-1 && echo "OK $d"
done
aws s3 ls s3://saira-images/arquivo-servidor-2026/ --region sa-east-1   # conferir 5 objetos com tamanho
```
(Precisa de credencial com `s3:PutObject` no bucket: a do `.env` hoje, ou o papel do passo 9.)

Depois, apagar (só as que deram `OK`):
```bash
sudo rm -rf $M/esp32_002/2026 $M/esp32_005/2026 $M/videos/pi-cam-001 $M/_archive_backlog_20260609 $M/bulk/*
```
Opção B: apagar direto, sem arquivar. Desfazer: só pela opção A (`aws s3 cp s3://.../X.tar - | sudo tar -C $M -xf -`, depois de restaurar do Deep Archive, que leva até 12 h).

### 3.2 Imagem e containers mortos (8,6 GB)

`esp32-server-fake-worker:latest` (8,58 GB) e `esp32-server-esp32-receiver:latest`, com os containers `esp32-server-fake-worker-1` e `esp32-server-esp32-receiver-1` em *Created* desde março (nunca rodaram).
```bash
docker ps -a --filter name=esp32-server- --format '{{.Names}} {{.Status}}'   # conferir: só os dois, Created
docker rm esp32-server-fake-worker-1 esp32-server-esp32-receiver-1
docker rmi esp32-server-fake-worker:latest esp32-server-esp32-receiver:latest
```
Desfazer: as imagens saem de `esp32-server/docker-compose.yml` (`docker compose build`), se um dia forem precisas.

### 3.3 Cache de build (1,7 GB)
```bash
docker builder prune -f
```
Risco: o próximo build demora mais. Pôr no cron já existente, depois do prune de imagens: `55 3 * * * docker builder prune -f --filter until=240h >> /home/ubuntu/logs/docker-builder-prune.log 2>&1`.

### 3.4 Logs dos containers (1,1 GB) e journal (~1 GB)
O PR põe teto (5 × 20 MB por container) a partir do próximo deploy. O que já existe:
```bash
L=$(docker inspect -f '{{.LogPath}}' saira-esp32-server-prod); sudo ls -la $L
sudo sh -c "tail -c 50000000 $L | gzip > /home/ubuntu/logs/esp32-server-prod-ate-$(date +%F).log.gz"   # guarda os últimos 50 MB
sudo truncate -s 0 $L
sudo journalctl --vacuum-size=500M
sudo mkdir -p /etc/systemd/journald.conf.d && printf '[Journal]\nSystemMaxUse=500M\n' | sudo tee /etc/systemd/journald.conf.d/teto.conf && sudo systemctl restart systemd-journald
```
Desfazer: não há (é log). Risco: perder log antigo, já guardado no `.gz`.

### 3.5 Volumes órfãos (~370 MB)
```bash
docker volume ls -qf dangling=true | wc -l          # ~200
docker volume prune -f                              # Docker 28: só os anônimos sem uso
# Bancos de projetos antigos. prod_postgres_data pode ser uma produção anterior: guardar antes.
mkdir -p /home/ubuntu/backups/volumes
docker run --rm -v prod_postgres_data:/v:ro -v /home/ubuntu/backups/volumes:/b alpine tar czf /b/prod_postgres_data-$(date +%F).tgz -C /v .
docker volume rm prod_postgres_data test_postgres_data_test services_postgres_data_test services_yolo_state_prod services_yolo_state_test
```
Desfazer: `docker volume create prod_postgres_data && docker run --rm -v prod_postgres_data:/v -v /home/ubuntu/backups/volumes:/b alpine tar xzf /b/prod_postgres_data-AAAA-MM-DD.tgz -C /v`.

### 3.6 Home do usuário (~12 GB)

| Item | Tamanho | Comando | Conferir antes |
|---|---:|---|---|
| `~/.git` (a home é um clone velho de jan/2026) | 4,0 GB | `rm -rf /home/ubuntu/.git` | `git -C /home/ubuntu log --oneline --branches --not --remotes` vazio (conferido em 24/11). Os arquivos da home ficam; só some o histórico, que está no GitHub. |
| `~/.vscode-server/cli/servers` (5 versões) | ~2,6 GB | apagar todas menos a mais nova: `cd ~/.vscode-server/cli/servers && ls -td Stable-* \| tail -n +2 \| xargs rm -rf` | nenhuma sessão do VS Code aberta (`pgrep -f vscode-server` vazio). Ele baixa de novo se precisar. |
| `$P/esp32-server/uploads` (uploads do **teste**, mar/jun) | 3,9 GB | `rm -rf $P/esp32-server/uploads` | fazer **depois** do passo 4 (o teste passa a usar `$T/esp32-server/uploads`) |
| `$P/tmp` (snapshots da esp32_005 de 11/03) | 0,9 GB | `rm -rf $P/tmp/esp32-005-2026-03-11*` | |
| `$P/esp32-server/backup_uploads.log.*` (março) | 0,4 GB | `rm $P/esp32-server/backup_uploads.log.2026*` | |
| `~/.gemini/history` | 1,7 GB | decisão sua (histórico do Gemini CLI) | |
| soltos: `picam_pull`, `last10`, `occ`, `evt_163625.mp4`, `lastframes_picam`, `leadup_picam`, `last_frames_picam` | ~0,6 GB | `rm -rf` depois de olhar | são capturas manuais de jul/ago |

## 4. Checkout próprio do teste

Hoje o teste e a produção usam o mesmo `/home/ubuntu/saira`, que o `deploy.yml` alterna entre `develop` e `main` com `git reset --hard`. Ele está em `develop` agora. A produção lê ao vivo deste checkout: `nginx/gateway.conf`, `prometheus.prod.yml`, `alert.rules.yml`, `alertmanager.prod.yml`, `observability/grafana/*` (o Grafana relê os dashboards sozinho), `yolo-worker-vm/models/`, `vertex-cred-config.json`, `esp32-server/config/` e `ota/`; e os crons de produção rodam scripts dele. O PR muda o job de teste para `/home/ubuntu/saira-test`, com o próprio `.env`. O job de produção não muda.

**Ordem: estes comandos vêm antes do merge do PR em `develop`** (o job novo falha com mensagem clara se `$T` não existir, sem tocar em nada).

Conferir antes: em 24/11 não havia diferença entre `main` e `develop` em nenhum arquivo montado pela produção:
```bash
cd $P && git fetch origin
git diff --stat origin/main origin/develop -- services/nginx services/observability services/yolo-worker-vm/models services/yolo-worker-vm/vertex-cred-config.json esp32-server/config esp32-server/ota services/yolo-worker-vm/scripts
# esperado: vazio. Se não for, ler o diff: é o que a produção vai deixar de ver.
git status --short   # não versionados: backups/, SPEC_WIREGUARD_EC2.md, PDFs (ficam)
```
Fazer:
```bash
cd $P
git checkout -B main origin/main             # produção volta a ver main (no-op para os montados, ver acima)
git worktree add -B develop $T origin/develop
cp -p $P/services/.env $T/services/.env      # o teste passa a ter o seu; depois enxugar
cp -p $P/esp32-server/.env $T/esp32-server/.env
chmod 600 $T/services/.env $T/esp32-server/.env
git -C $T log -1 --oneline                   # = origin/develop
```
O teste continua no ar com os containers atuais até o próximo deploy de `develop` (o do merge do PR), que recria tudo a partir de `$T`. Os volumes do teste têm o mesmo nome (projeto `saira-test`), então o banco de teste continua. Os uploads de teste passam a ser `$T/esp32-server/uploads` (vazio); os antigos saem no passo 3.6.

Depois de um deploy de teste verde: tirar do `.env` da produção as variáveis `TEST_*` e do `.env` do teste as que só a produção usa. Mais adiante, o compose de teste pode ler nomes sem `TEST_` do próprio `.env` (mudança grande de compose; fica para quando a frente do funil A tiver terminado de mexer nele).

Desfazer: `git -C $P worktree remove $T` e reverter o commit do `deploy.yml`.

Risco: `git checkout -B develop` dentro de `$P` passa a falhar (o branch está no worktree). Nenhum job faz isso depois do PR.

## 5. Cópias `.env.bak*` (31 arquivos)

Em `$P/services/`: 29 `.env.bak*` de 12/03 a 24/08/2026 (15 B a 3 kB, ~63 kB), mais `.env.vpn.bak_` (90 B). 30 delas têm permissão `664` (qualquer usuário do host lê).

Recomendação: guardar **uma** cópia cifrada de todas no repositório Envs (git-crypt) e apagar do servidor. Guardar todas juntas custa nada e preserva o histórico de flags (os nomes contam a história: `pre_poll180`, `c51off`, `shadowbedrock`...).
```bash
cd $P/services && ls -la .env.bak* .env.vpn.bak_ | wc -l        # 31
tar czf /tmp/saira-env-bak-$(date +%F).tgz .env.bak* .env.vpn.bak_ && chmod 600 /tmp/saira-env-bak-*.tgz
# no PC: scp saira-prod:/tmp/saira-env-bak-AAAA-MM-DD.tgz C:\secrets\Envs\saira\  (pasta coberta pelo .gitattributes do git-crypt)
# no PC: cd C:\secrets\Envs; git-crypt status saira/ (tem de dizer "encrypted"); git add; git commit; git push
# conferir que o commit saiu cifrado: git show --stat HEAD; git-crypt status -e | findstr saira
rm /tmp/saira-env-bak-*.tgz && rm .env.bak* .env.vpn.bak_
```
Daqui para frente, backup do `.env` só fora do servidor (ou `chmod 600` e apagar depois de uma semana). Desfazer: extrair o `.tgz` do Envs.

## 6. Merge do PR de infraestrutura e deploy

O PR (para `develop`) muda:
- portas internas só em `127.0.0.1`: produção 3000, 5000, 8001, 5432; teste 3001, 5001, 8002, 5433, 5051, 3004, 9091, 9108, 9109. Ficam abertas só as de câmera (5005, 5002), por bind; o Security Group fecha o resto;
- `SECRET_KEY` e `TEST_SECRET_KEY` obrigatórias;
- senhas do Postgres, Grafana e pgAdmin por variável (com o valor atual como padrão: nada muda até o passo 7);
- log com teto em todos os containers;
- checkout próprio do teste no `deploy.yml`;
- worker: quadros de câmera inativa saem do disco (desligado até o passo 8).

Pré-requisitos: passos 2 e 4 feitos. Sem o passo 2 o deploy falha antes de recriar qualquer container (`required variable SECRET_KEY is missing`), o que é seguro mas para os deploys de `develop`.

Quem acessa as portas que fecham: o cloudflared chega por `localhost` (3000, 3001, 5000, 5001); os containers se falam pela rede Docker; Grafana, Prometheus e Postgres de fora só por túnel SSH (`ssh -L 5432:127.0.0.1:5432 saira-prod`). Nenhum cliente de fora foi visto nos logs (Postgres: só 172.22.0.x; gateway: só scanners).

Depois do deploy de teste: `ss -tlnp | grep docker-proxy` deve mostrar `127.0.0.1` em todas, menos 5002 e 5005. A produção só muda quando você fizer o merge de `develop` em `main`.

Detalhe: o cloudflared usa `http://localhost:PORTA`; o Go tenta `::1` e depois `127.0.0.1`, então funciona. Para não depender disso, trocar `localhost` por `127.0.0.1` em `/etc/cloudflared/config.yml` no mesmo dia.

## 7. Trocar as senhas padrão

As três senhas só valem na criação do volume: mudar a variável sem mudar dentro do serviço derruba a conexão. Ordem certa, uma por vez. Use só `[0-9a-f]` (a do Postgres vai dentro do `DATABASE_URL`).

**Postgres de produção** (backend e worker reconectam; ~30 s sem gravar):
```bash
NEW=$(openssl rand -hex 24)
docker exec saira-db-prod psql -U postgres -c "ALTER USER postgres PASSWORD '$NEW'"   # conexões abertas continuam
echo "POSTGRES_PASSWORD=$NEW" >> $P/services/.env
cd $P/services && docker compose -p saira-prod --profile worker -f docker-compose.prod.yml up -d --no-deps backend yolo-worker   # os dois únicos que usam o DATABASE_URL
docker logs --since 2m saira-backend-prod 2>&1 | grep -ci 'password authentication failed'   # esperado: 0
```
Desfazer: `ALTER USER postgres PASSWORD 'postgres'`, tirar a linha e recriar os mesmos dois.
Teste: o mesmo com `saira-db-test`, `TEST_POSTGRES_PASSWORD` em `$T/services/.env` e o projeto `saira-test`.

**Grafana** (produção e teste):
```bash
docker exec saira-grafana-prod grafana cli admin reset-admin-password "$(openssl rand -hex 16)"
```
e grave a mesma senha em `GRAFANA_ADMIN_PASSWORD` (teste: `TEST_GRAFANA_ADMIN_PASSWORD`) para o caso de recriar o volume.
**pgAdmin de teste:** trocar pela tela (File → Change Password) e gravar em `TEST_PGADMIN_PASSWORD`. Ou tirar o pgAdmin do teste: com a porta no loopback, ele só é usado por túnel.

## 8. Variáveis do worker para as Pi

- **`POLL_INTERVAL=10` em produção** (hoje 180; o teste usa 5). O worker dorme `POLL_INTERVAL` entre varreduras (`main.py`, fim do loop). Nas Pi (`EVENT_DRIVEN_DEVICES`) a câmera fecha o evento e o worker só o pega na varredura seguinte: com 180 o alerta espera até 3 min a mais; com 10, até 10 s. Uma varredura custa um `glob` nos manifestos de cada Pi (32 mil arquivos na pi-cam-001 hoje), barato a cada 10 s. Os 180 vieram das ESP32 (`.env.bak_pre_poll180_20260521`): no caminho por janelas de tempo, a janela em aberto é processada na varredura, então intervalo curto quebra a janela em pedaços e multiplica chamadas ao modelo. **Se alguma ESP32 voltar a ficar ativa, volte para 180 ou corrija esse caminho antes.**
- **`INACTIVE_DEVICE_MAX_FRAME_AGE_SECONDS=3600`** (produção) e `TEST_INACTIVE_DEVICE_MAX_FRAME_AGE_SECONDS=3600` (teste). Quadros brutos de câmera sem cadastro ativo, com mais de 1 h, vão para `sem_ocorrencia` sem IA; a migração das 03:00 zipa para o S3 e apaga. Não passe de ~3 h: a migração só pega o dia anterior, e um quadro movido depois das 03:00 do dia seguinte fica no disco. Ligar **depois** do passo 3.1 (senão a primeira varredura move 14 GB para pastas de datas velhas que a migração não pega).

- **`EVENT_MANIFEST_ARCHIVE_AFTER_SECONDS=172800`** (2 dias; teste: `TEST_EVENT_MANIFEST_ARCHIVE_AFTER_SECONDS`). Nada apagava os manifestos de evento: a pi-cam-001 juntou 31.943 (~444 por dia, mais `.lock` e `.processed`), e cada varredura lê todos duas vezes. Medido no servidor em 24/11: **0,85 s por leitura** com uma Pi. Com 6 Pi por um ano seriam ~1 milhão de manifestos e dezenas de segundos por varredura, e aí o `POLL_INTERVAL` deixa de importar. Com a variável, os processados há mais de 2 dias vão para `events/arquivo/AAAAMM/` (fora da leitura), no máximo uma vez por hora por câmera. Os 2 dias de folga evitam reprocessar um evento que receba atualização atrasada.

```bash
cd $P/services && cp -p .env .env.bak-poll-$(date +%Y%m%d)
sed -i 's/^POLL_INTERVAL=180$/POLL_INTERVAL=10/' .env && grep '^POLL_INTERVAL=' .env
echo 'INACTIVE_DEVICE_MAX_FRAME_AGE_SECONDS=3600' >> .env
echo 'EVENT_MANIFEST_ARCHIVE_AFTER_SECONDS=172800' >> .env
docker compose -p saira-prod --profile worker -f docker-compose.prod.yml up -d --no-deps yolo-worker
docker logs --since 1m saira-yolo-worker-prod 2>&1 | grep POLL_INTERVAL     # 10s
```
(`INACTIVE_DEVICE_*` e `EVENT_MANIFEST_*` só têm efeito depois que o PR chegar em `main`. Desfazer o arquivamento: `mv events/arquivo/*/* events/`.) Desfazer: voltar o `.env` e recriar o worker.

## 9. IAM Role no lugar das chaves estáticas

Medido: a instância **já tem** o papel `SAIRA` anexado, e os containers alcançam o IMDS (testado no worker de teste: devolve o papel `SAIRA`). O código já usa a cadeia padrão do boto3 quando `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` estão vazias (`storage_s3.py`, `detector_bedrock.py`, backend `services/s3.py`). Falta dar a permissão ao papel e tirar as chaves.

Política mínima (em linha no papel `SAIRA`, pelo console ou `codex-ops`):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "ImagensS3", "Effect": "Allow",
     "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
     "Resource": "arn:aws:s3:::saira-images/*"},
    {"Sid": "ListarBucket", "Effect": "Allow", "Action": "s3:ListBucket",
     "Resource": "arn:aws:s3:::saira-images"},
    {"Sid": "GateNovaLite", "Effect": "Allow", "Action": "bedrock:InvokeModel",
     "Resource": [
       "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
       "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
       "arn:aws:bedrock:us-east-1:818680680175:inference-profile/us.amazon.nova-lite-v1:0"
     ]}
  ]
}
```
(`ListBucket` faz o `head_object` de chave ausente dar 404 em vez de 403. O bloco do Bedrock é o do funil A; outros modelos entram só se forem ligados. Conferir antes, pelo `codex-readonly`, o que o papel já tem: `aws iam list-attached-role-policies --role-name SAIRA` e `list-role-policies`.)

Passos:
1. Anexar a política. Testar do host, sem as chaves: `env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY aws s3 ls s3://saira-images/ --region sa-east-1 | head -3`.
2. **Backend:** as URLs assinadas de exportação valem 24 h (`EXPORT_PRESIGNED_TTL_SECONDS=86400`), mas uma URL assinada com credencial do papel morre quando a credencial expira (algumas horas). Antes de tirar a chave do backend, pôr `EXPORT_PRESIGNED_TTL_SECONDS=3600`: o backend já renova a URL quando falta menos de 1 h (`exports.py`, `_maybe_refresh_url`), então cada abertura sai com uma URL nova.
3. Tirar as duas linhas do `.env` (produção e teste), recriar `backend` e `yolo-worker` e acompanhar a migração das 03:00 no dia seguinte (`docker logs saira-yolo-worker-prod | grep 'S3 sync complete'`).
4. Desativar a chave estática no IAM (não apagar ainda); apagar depois de 7 dias sem erro.

Desfazer: devolver as duas linhas ao `.env` e reativar a chave.

## 10. Flags e crons residuais

| Item | Medido em 24/11 | Recomendação |
|---|---|---|
| `CAR_SHADOW_ENABLED=true` (produção e teste) | carrega o YOLO de carros no início e roda em sombra | desligar (`false`) até haver campanha que use o resultado; poupa memória e CPU por quadro |
| `DINOV2_FILTER_MODE=shadow` + cron de retreino (domingo 07:10 UTC) | último retreino 22/11: `GATE FAIL auc 0,767 < 0,85`, nada trocado | desligar o modo (`off`) e comentar o cron até a volta; o retreino não passa no próprio portão |
| `recalibrate_bgsub_cron.sh` (04:30 e 12:30 UTC) | falha 2×/dia: `esp32_005: no sem_ocorrencia frames found`; tem `docker restart` do worker de produção no fim (não chega lá por causa do `set -e`) | comentar a linha; câmera ESP32 não volta |
| `/opt/pi-recovery-capture/capture_on_recovery.py` (a cada 2 min) | desarmado desde 09/09 (`cron.log` vazio) | comentar a linha e apagar a pasta depois |
| tabela `detections_image_url_backup_placehold_20260309` (224 kB) | ninguém usa | `pg_dump -t` para `/home/ubuntu/backups` e `DROP TABLE` |
| `/opt/4g-monitor/*` (root, a cada 5 min e diários) | ativos | manter se o 4G das Pi voltar; senão comentar |
| peer WireGuard 10.8.0.2 | último handshake há 173 dias | tirar do `wg0.conf` se for aparelho aposentado |

Crons, antes de mexer: `crontab -l > /home/ubuntu/crontab.bak.$(date +%Y%m%d)`; desfazer: `crontab /home/ubuntu/crontab.bak.AAAAMMDD`. Flags: no `.env`, recriar o worker; desfazer voltando o valor.

## 11. Security Group (`launch-wizard-3` e `SairaCam`)

Não li as regras (login `codex sso` vencido em 24/11). Visto de fora, do IP de casa: **abertas 22, 5000, 5001, 5002, 5005**; filtradas as demais (3000, 3001, 3004, 5003, 5051, 5432, 5433, 8001, 8002, 9091, 9092, 9108, 9109, 6379). Pode haver regra para outros IPs.

Ler (perfil de leitura):
```bash
aws sso login --sso-session "codex sso" --use-device-code --no-browser
aws ec2 describe-security-groups --profile codex-readonly --region us-east-1 \
  --filters Name=group-name,Values=launch-wizard-3,SairaCam \
  --query 'SecurityGroups[].{g:GroupName,in:IpPermissions[].{p:FromPort,to:ToPort,proto:IpProtocol,cidr:IpRanges[].CidrIp}}'
```
Recomendação para janeiro (só Pi, pelo WireGuard):
- **manter** 22 (de preferência só do seu IP e dos IPs do GitHub Actions, ou trocar o deploy por SSM) e a UDP 51820 do WireGuard;
- **fechar** 5000 e 5001 (o tráfego legítimo entra pelo Cloudflare; nos logs só há scanners), 5002 e 5005 (a Pi fala por `10.8.0.1`; o que chega pela internet é ESP32 aposentada e scanner);
- conferir se há regra para 5432, 8001 ou outra interna e tirar.

Antes de fechar 5005: `docker logs --since 72h saira-esp32-server-prod 2>&1 | awk '{print $1}' | sort | uniq -c | sort -rn | head` e confirmar que nada legítimo chega por IP público. Desfazer: recriar a regra.

## 12. Expansão do EBS (só se precisar)

Depois da limpeza o disco fica em ~35 GB de 96 (~36%). Para as Pi o crescimento é pequeno: a pi-cam-001 gerou ~154 MB de manifestos e quadros rotulados em três meses (os quadros vão para o S3 todo dia); o que mais pesa é o rebuild do worker (~7 GB por imagem nova até o prune de 10 dias). **Não recomendo expandir agora.** Se o disco passar de 80% em janeiro:

- custo: gp3 em us-east-1 a US$ 0,08 por GB-mês (gp2: US$ 0,10). +50 GB = US$ 4,00/mês (gp3) ou US$ 5,00 (gp2). Conferir o tipo: `aws ec2 describe-volumes --profile codex-readonly --filters Name=attachment.instance-id,Values=i-092cb60f61bd503e3`;
- passos (sem desligar): snapshot do volume; `aws ec2 modify-volume --volume-id vol-... --size 150` (com `codex-ops`); no servidor `sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/nvme0n1p1 && df -h /`. Desfazer: não dá para diminuir um EBS (só com volume novo e cópia).
