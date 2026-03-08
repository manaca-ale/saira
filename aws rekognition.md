# Plano Global - Opcao AWS Rekognition no SAIRA

## Global Sprint Overview
Objetivo: adicionar o AWS Rekognition como opcao de motor de IA no `yolo-worker`, mantendo YOLO como opcao atual e permitindo trocar o provedor por variavel de ambiente, sem quebrar o fluxo existente (`upload -> worker -> db -> notificacoes -> frontend`).

Resultado esperado ao final:
- `AI_MODEL_PROVIDER=yolo` continua funcionando como hoje.
- `AI_MODEL_PROVIDER=rekognition` ativa deteccao via AWS Rekognition padrao (sem Custom Labels).
- `AI_MODEL_PROVIDER=mock` continua disponivel para testes locais.
- Rollback imediato por troca de variavel + restart do container do worker.

Assumicoes usadas neste plano:
- O ponto de integracao principal e `services/yolo-worker-vm/src/worker/`.
- O worker continua sendo o unico responsavel por inferencia.
- Rekognition sera usado com `DetectLabels`.
- Para lixo, a resposta funcional sera binaria: `tem lixo` ou `nao tem lixo`.
- Para infratores, tambem sera sem Custom Labels, usando labels padrao.

Escopo imediato (fase atual):
- Executar e validar tudo localmente.
- Nao fazer deploy em servidor (test/prod) nesta fase.
- Qualquer passo de deploy fica registrado apenas como fase 2, apos validacao local.

## Arquitetura alvo (alto nivel)
1. Introduzir um seletor unico de provedor:
- `AI_MODEL_PROVIDER=yolo|rekognition|mock`

2. Manter contrato unico de inferencia:
- `load_models(...)`
- `detect_garbage(image_path, conf=...) -> (detections, annotated_image)`
- `detect_infrators(image_path, conf=...) -> list[detections]`

3. Implementar `detector_rekognition.py` com:
- cliente boto3 Rekognition;
- chamadas `DetectLabels` para lixo (regra binaria);
- chamadas `DetectLabels` para infratores;
- normalizacao de output para o mesmo formato usado hoje pelo pipeline.

4. Sem alteracao de schema de banco nesta fase:
- campos existentes (`waste_type`, `offenders`, `confidence_score`, etc.) continuam sendo preenchidos.
- para lixo binario, `waste_type` pode ser padronizado como `Lixo detectado` (ou manter `Entulho` por compatibilidade), definido em regra unica no worker.

## Implementation Roadmap
### Step 1: Shared Dependencies / Infrastructure
- Definir padrao de variaveis para escolha de provedor e parametros AWS.
- Garantir autenticacao AWS segura para teste local (chaves ou profile local). IAM Role em servidor fica para fase 2.
- Definir regiao unica por ambiente (default atual: `us-east-1`, que ja esta liberada no servidor).
- Definir teto de custo por chamadas de API (sem custo de modelo em estado RUNNING).

### Step 2: Task-by-Task Breakdown
#### Task: Introduzir provider switch no worker
- **Affected Files**: `services/yolo-worker-vm/src/worker/config.py`, `services/yolo-worker-vm/src/worker/main.py`
- **Key Logic**:
  - Adicionar `AI_MODEL_PROVIDER` com default `yolo`.
  - Remover ambiguidade entre `MOCK_MODE` e provider (mock deve ser um provider explicito).
  - Em `main.py`, selecionar modulo de detector por provider:
    - `yolo` -> `detector_yolo`
    - `rekognition` -> `detector_rekognition`
    - `mock` -> `detector_mock`
  - Em provider invalido, falhar rapido com log claro.

#### Task: Implementar detector Rekognition (sem Custom Labels)
- **Affected Files**: `services/yolo-worker-vm/src/worker/detector_rekognition.py` (novo), `services/yolo-worker-vm/src/worker/main.py`
- **Key Logic**:
  - Criar cliente boto3 com suporte a credenciais de ambiente/role.
  - Ler imagem local e enviar bytes para Rekognition (`DetectLabels`).
  - Lixo (binario):
    - aplicar regra por lista de labels candidatas (ex.: `Garbage`, `Trash`, `Waste`, `Debris`, `Litter`, `Junk`, `Refuse`, `Landfill`).
    - se houver ao menos 1 label candidata acima do threshold -> `tem lixo`; caso contrario -> `nao tem lixo`.
    - retornar `current_count=1` quando `tem lixo` e `0` quando `nao tem lixo` para preservar a logica atual de transicao do worker.
  - Infratores (sem custom):
    - usar labels padrao como `Person`, `Car`, `Truck`, `Bus`, `Motorcycle`, `Bicycle`.
    - mapear para `Pessoa|Carro|Moto|Outro`.
  - Quando Rekognition nao retornar bounding boxes uteis para todos os labels, usar anotacao fallback (texto no frame) para manter `image_url` e rastreabilidade visual.

#### Task: Definir variaveis de ambiente e defaults
- **Affected Files**: `services/.env.example`, `services/docker-compose.yml`
- **Key Logic**:
  - Adicionar no `yolo-worker`:
    - `AI_MODEL_PROVIDER=yolo`
    - `AWS_REGION=us-east-1`
    - `REKOGNITION_WASTE_DECISION_MODE=binary`
    - `REKOGNITION_WASTE_LABELS=Garbage,Trash,Waste,Debris,Litter,Junk,Refuse,Landfill`
    - `REKOGNITION_WASTE_MIN_CONFIDENCE=70`
    - `REKOGNITION_OFFENDER_MODE=detect_labels|disabled`
    - `REKOGNITION_OFFENDER_LABELS=Person,Car,Truck,Bus,Motorcycle,Bicycle`
    - `REKOGNITION_OFFENDER_MIN_CONFIDENCE=70`
    - `REKOGNITION_MAX_LABELS=50`
    - `REKOGNITION_MAX_RETRIES=3`
    - `REKOGNITION_TIMEOUT_SECONDS=10`
    - `AI_FALLBACK_PROVIDER=none|yolo`
  - Nao versionar secrets reais no repositorio.
  - Mudancas em `docker-compose.test.yml` e `docker-compose.prod.yml` ficam para fase 2.

#### Task: Dependencias e build do worker
- **Affected Files**: `services/yolo-worker-vm/requirements.txt`, `services/yolo-worker-vm/Dockerfile`
- **Key Logic**:
  - Garantir `boto3` e `botocore` no worker.
  - Manter OpenCV para anotacao da imagem.
  - Validar build local com novo provider.

#### Task: Configuracoes AWS (conta, IAM, custo)
- **Affected Files**: `services/docs/runbooks/yolo-vm.md`, `services/docs/runbooks/operations.md` (preencher), `aws rekognition.md` (esta especificacao)
- **Key Logic**:
  - Criar configuracao AWS minima para desenvolvimento local primeiro.
  - Preferir credencial local de baixo privilegio nesta fase.
  - Permissoes minimas de inferencia:
    - `rekognition:DetectLabels`
  - Se houver automacao de verificacao de disponibilidade/limites, adicionar somente permissoes estritamente necessarias.
  - Habilitar AWS Budgets para limite de custo (ao menos um alerta basico).

#### Task: Calibracao da regra binaria de lixo e labels de infrator
- **Affected Files**: `services/docs/runbooks/yolo-vm.md`, `services/test_worker_integration.py` (cenarios), testes do worker
- **Key Logic**:
  - Coletar lote real de imagens SAIRA (com e sem lixo).
  - Rodar Rekognition e registrar labels retornadas com score.
  - Ajustar lista `REKOGNITION_WASTE_LABELS` e threshold para reduzir falso positivo/negativo.
  - Ajustar lista/threshold de infratores para reduzir ruido (`Vehicle` generico, por exemplo).
  - Congelar baseline local em runbook.

#### Task: Resiliencia, timeout e fallback
- **Affected Files**: `services/yolo-worker-vm/src/worker/detector_rekognition.py`, `services/yolo-worker-vm/src/worker/main.py`
- **Key Logic**:
  - Implementar retry com backoff para throttling/transient errors.
  - Definir timeout de chamada para nao travar ciclo do worker.
  - Se `AI_FALLBACK_PROVIDER=yolo`, cair para YOLO quando AWS estiver indisponivel.
  - Logar motivo do fallback e contador de erros consecutivos.

#### Task: Testes automatizados e validacao end-to-end
- **Affected Files**: `services/test_worker_integration.py`, `services/yolo-worker-vm/src/worker/` (novos testes unitarios), pipeline de testes se existir
- **Key Logic**:
  - Testes unitarios do mapeamento de labels AWS -> binario de lixo.
  - Testes unitarios do mapeamento de labels AWS -> tipos de infrator SAIRA.
  - Testes unitarios de selecao de provider via env.
  - Teste de integracao com `botocore.stub.Stubber` (sem chamada real AWS).
  - E2E manual:
    - subir stack local (`docker-compose.yml`);
    - definir `AI_MODEL_PROVIDER=rekognition`;
    - enviar imagens;
    - validar `detections`, `detection_offenders`, notificacoes e `image_url`.

#### Task: Deploy e operacao em servidor
- **Affected Files**: `.github/workflows/deploy.yml`, `services/docs/docker-comandos-uteis.md`, `services/docs/runbooks/operations.md`
- **Key Logic**:
  - Fora do escopo da fase atual (local only).
  - Manter como backlog para fase 2 apos validacao local.

## Configuracao AWS detalhada (execucao)
### 1. Conta e governanca
1. Criar/selecionar conta AWS separada para SAIRA (ou ao menos segregacao por ambiente).
2. Ativar MFA para usuarios administrativos.
3. Configurar AWS Budgets e alarme de billing (email/Slack).

### 2. Regiao
1. Definir regiao padrao (`us-east-1` no estado atual de permissoes).
2. Garantir que worker e Rekognition usem a mesma regiao configurada.

### 3. IAM para inferencia
1. Preferencial: criar IAM Role para a instancia/host do worker.
2. Politica minima:
   - `rekognition:DetectLabels`
3. Em dev local, IAM User com a mesma politica minima (sem permissoes administrativas).

### 4. Estrategia sem Custom Labels
1. Nao criar projetos de Rekognition Custom Labels.
2. Definir e versionar internamente (runbook) a taxonomia de labels aceitas para:
   - lixo binario;
   - infratores.
3. Revisar periodicamente a taxonomia com base em amostras reais de campo.

### 5. Operacao de custo (API calls)
1. Monitorar custo por quantidade de chamadas `DetectLabels`.
2. Definir limites por ambiente e alertas preventivos.
3. Ajustar `POLL_INTERVAL` e filtros para evitar chamadas desnecessarias.

## Variaveis de ambiente finais (alvo)
- `AI_MODEL_PROVIDER=yolo|rekognition|mock`
- `AWS_REGION=us-east-1`
- `AWS_ACCESS_KEY_ID=` (apenas quando nao houver IAM Role)
- `AWS_SECRET_ACCESS_KEY=` (apenas quando nao houver IAM Role)
- `REKOGNITION_WASTE_DECISION_MODE=binary`
- `REKOGNITION_WASTE_LABELS=Garbage,Trash,Waste,Debris,Litter,Junk,Refuse,Landfill`
- `REKOGNITION_WASTE_MIN_CONFIDENCE=70`
- `REKOGNITION_OFFENDER_MODE=detect_labels|disabled`
- `REKOGNITION_OFFENDER_LABELS=Person,Car,Truck,Bus,Motorcycle,Bicycle`
- `REKOGNITION_OFFENDER_MIN_CONFIDENCE=70`
- `REKOGNITION_MAX_LABELS=50`
- `REKOGNITION_MAX_RETRIES=3`
- `REKOGNITION_TIMEOUT_SECONDS=10`
- `AI_FALLBACK_PROVIDER=none|yolo`

## Estrategia de rollout
1. Implementar e validar em ambiente local com `mock`.
2. Validar local com `AI_MODEL_PROVIDER=rekognition`.
3. Rodar comparacao local controlada (A/B) com YOLO:
   - manter YOLO como referencia por periodo;
   - comparar taxa de deteccao e falsos positivos.
4. Congelar checklist de deploy para fase 2 (sem executar deploy agora).
5. Manter rollback imediato para `AI_MODEL_PROVIDER=yolo`.

## Global Definition of Done
- [ ] Worker seleciona corretamente `yolo`, `rekognition` ou `mock` via `AI_MODEL_PROVIDER`.
- [ ] Com `AI_MODEL_PROVIDER=rekognition`, pipeline ponta-a-ponta funciona e grava deteccoes.
- [ ] Deteccao de lixo em Rekognition funciona em modo binario (`tem lixo`/`nao tem lixo`).
- [ ] Deteccao de infratores funciona com labels padrao do Rekognition (sem custom).
- [ ] Notificacoes e SSE seguem funcionando sem alteracao funcional.
- [ ] `image_url` continua apontando para imagem anotada servida pelo `esp32-server`.
- [ ] Configuracoes AWS de IAM e operacao estao documentadas em runbook.
- [ ] Custos monitorados com Budgets/Alarmes.
- [ ] Teste local completo validado em `docker-compose.yml` sem deploy remoto.
- [ ] Rollback validado (troca para `AI_MODEL_PROVIDER=yolo` + restart do worker).
- [ ] UTF-8/LF garantidos nos arquivos alterados.

## Conflict Risks
- Labels padrao do Rekognition nao refletirem bem cenarios reais de descarte.
- Ambiguidade semantica de labels genericas causar falso positivo de lixo.
- Latencia/rede AWS aumentar tempo de ciclo do worker.
- Credenciais AWS mal configuradas causarem falha total de deteccao.
- Fallback mal definido gerar comportamento silencioso e dificil de monitorar.

## Plano de execucao recomendado (ordem)
1. Padronizar variaveis e provider switch no codigo.
2. Implementar `detector_rekognition.py` com regra binaria de lixo e labels de infrator.
3. Configurar AWS (IAM + custo + observabilidade).
4. Conectar envs no compose local e validar localmente.
5. Atualizar runbooks operacionais da fase local.
6. Registrar fase 2 (deploy servidor) sem executar nesta etapa.
