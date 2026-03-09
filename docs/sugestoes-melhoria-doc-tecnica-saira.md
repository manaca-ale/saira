# Sugestoes Revisadas - Documento Tecnico SAIRA

## Contexto da revisao
Esta versao revisa as sugestoes anteriores com base no codigo atual do projeto (frontend + backend), para manter o documento como **apresentacao do que foi entregue no MVP** e nao como especificacao futura.

## Ajustes feitos em relacao a versao anterior
1. Remocao de itens que nao estao implementados no dashboard principal (ex.: taxa de resolucao e tempo medio como KPI do card principal).
2. Remocao de filtros que nao existem na tela do dashboard (ex.: filtro por camera/dispositivo na barra principal).
3. Ajuste da parte de tempo real: hoje o SSE atualiza notificacoes (drawer/toast), nao os cards e graficos do dashboard automaticamente.
4. Remocao de afirmacoes fortes de controle por perfil no dashboard, pois o codigo atual nao aplica matriz completa de autorizacao por role nesse modulo.
5. Reescrita em tom de consolidacao do realizado, com foco descritivo.

## Texto revisado sugerido (copiar/colar)

### Substituir a secao `6. Dashboard e Funcionalidades`

#### 6. Dashboard e Funcionalidades
O dashboard web do SAIRA foi implementado como a camada de visualizacao operacional do MVP, consolidando ocorrencias detectadas, contexto geoespacial e acoes de tratamento. A pagina foi organizada em duas abas principais: **Dashboard de ocorrencias** e **Dashboard de Infratores**.

#### 6.1 Estrutura da tela implementada
No fluxo de ocorrencias, a tela apresenta:
- bloco de monitoramento com acao rapida **Ao Vivo**;
- barra de filtros com opcoes principais e filtros avancados;
- mapa georreferenciado com popup detalhado por ponto;
- cards de indicadores e grafico de ocorrencias por periodo;
- listas de locais reincidentes e volumetria por RPA;
- modal de ocorrencia com acoes operacionais.

No fluxo de infratores, a tela apresenta:
- cards de indicadores de reincidencia;
- graficos por tipo de infrator, volume, reincidencia e distribuicoes;
- ranking de placas mais reincidentes;
- distribuicao por cor de veiculo;
- acao de cadastro de novo infrator.

#### 6.2 Filtros implementados no Dashboard de ocorrencias
Os filtros disponiveis na interface sao:
- periodo (presets de 7 dias, 30 dias e ultimo ano, alem de intervalo manual por data e hora);
- status da ocorrencia;
- logradouro;
- bairro;
- RPA;
- tipo de residuo (filtro avancado);
- faixa de volumetria em m3 (filtro avancado);
- infratores identificados/nao identificados (filtro avancado).

Implementacao observada:
- a busca inicial de deteccoes utiliza o endpoint paginado `/api/v1/detections/search`;
- parte dos filtros e aplicada no cliente para recomputar indicadores, mapa e listas;
- o botao **Ao Vivo** ajusta filtros para priorizar ocorrencias com status aberto (Pendente e Em analise).

#### 6.3 Indicadores e visualizacoes entregues (ocorrencias)
No dashboard de ocorrencias, foram implementados:
- **Total de ocorrencias no periodo** (card);
- **Volume de residuos no periodo (m3)** (card);
- **Grafico de ocorrencias por periodo** com granularidade dinamica (hora, dia, semana ou mes, conforme o intervalo selecionado);
- **Locais reincidentes** (top 5 por frequencia);
- **Media de volumetria por RPA no periodo** (lista resumida).

#### 6.4 Mapa e interacao geoespacial
O componente de mapa suporta dois modos configuraveis por ambiente:
- **heatmap**, para intensidade de volume;
- **bubble map**, com cor por status e tamanho por volumetria.

Funcionalidades implementadas no mapa:
- popup com bairro, logradouro, horario, tipo/volume, status e indicador de infrator;
- botao **Ver Foto** no popup, abrindo o modal de ocorrencia;
- legenda visual e painel de configuracao de camadas;
- deduplicacao de pontos por coordenada, mantendo o registro mais recente por local.

#### 6.5 Modal de ocorrencia e acoes de tratamento
O modal de ocorrencia foi implementado com:
- imagem da evidencia;
- status, identificador, data/hora;
- logradouro, bairro, RPA;
- latitude/longitude;
- tipo de residuo, tipo de material e volumetria;
- lista de infratores vinculados.

Acoes disponiveis:
- marcar em analise (quando status atual e Pendente);
- marcar como resolvido (com coleta de data, setor encaminhado e justificativa);
- vincular/desvincular infratores;
- exportar ficha da ocorrencia em PNG/PDF;
- abrir coordenadas no Google Maps.

#### 6.6 Dashboard de Infratores implementado
A aba de infratores consome endpoints dedicados e entrega:
- KPIs: total de infratores, infratores reincidentes, alta reincidencia, placas identificadas e volume estimado;
- distribuicao de tipos de infrator;
- reincidencia por tipo;
- volume descartado por tipo;
- composicao de tipo de lixo por tipo de infrator;
- ranking de placas mais reincidentes;
- distribuicao por cor de veiculo;
- acao de cadastro de infrator diretamente na aba.

#### 6.7 Notificacoes e atualizacao em tempo real
O fluxo em tempo real implementado no MVP esta concentrado no modulo de notificacoes:
- backend publica eventos em Redis por usuario e canal global;
- frontend abre stream SSE em `/api/v1/notifications/stream`;
- notificacoes chegam em drawer e toast, com incremento de nao lidas;
- banner de login destaca ocorrencias registradas desde o ultimo acesso.

Observacao de escopo atual:
- os componentes do dashboard (cards/mapa/graficos) nao sao atualizados por SSE em tempo real; eles sao atualizados a partir de recarga de dados por consulta.

#### 6.8 Observacoes de consistencia para o documento final
Para refletir com precisao o que foi entregue no codigo atual:
- evitar afirmar controle de permissao detalhado por role dentro do dashboard;
- manter os nomes de status conforme uso no sistema: **Pendente**, **Em analise**, **Resolvido**;
- registrar que o dashboard de infratores aplica subconjunto dos filtros globais (periodo, logradouro, bairro e RPA unica).

---

### Texto revisado sugerido para secao 3 (pipeline de IA)

#### 3. Pipeline de Deteccao Ponta a Ponta (implementacao do MVP)
No MVP entregue, a pipeline de IA foi implementada com processamento assíncrono por varredura de diretorio, detecção em dois modelos YOLO (resíduo e infrator), persistência no PostgreSQL e notificações em tempo real via Redis + SSE.

#### 3.1 Captura e ingestao de imagem (borda -> servidor)
O firmware ESP32-CAM captura periodicamente uma foto e envia via `POST /upload` (multipart com campo `imageFile`) para o ESP32 Server. O servidor:
- valida o `X-Device-Id` (com fallback para `unknown_device`);
- grava o arquivo em `uploads/<device_id>/YYYY/MM/DD/<timestamp>.jpg`;
- registra evento operacional local;
- retorna `image_url` para rastreabilidade.

#### 3.2 Descoberta de novas imagens pelo Worker
O Worker YOLO roda em loop continuo e, a cada `POLL_INTERVAL`, varre `UPLOAD_DIR` em busca de novos `.jpg` ainda nao processados. Para cada pasta de dispositivo:
- resolve a camera no banco por `device_id` (somente cameras ativas);
- ignora imagens ja processadas;
- processa em ordem de nome de arquivo (timestamp).

#### 3.3 Inferencia de IA (P1 + P2)
No inicio do processo, o worker carrega dois modelos:
- **P1 (residuos)**: identifica classes de descarte e mapeia para `waste_type` do banco;
- **P2 (infratores)**: identifica pessoa/veiculo e mapeia para `offender_type`.

Quando os pesos nao estao disponiveis, o worker ativa automaticamente `MOCK_MODE`, mantendo a pipeline funcional para testes end-to-end.

#### 3.4 Regra de disparo de ocorrencia (logica de evento)
Para cada dispositivo, o worker persiste estado local em `STATE_DIR/<device_id>.json` com `last_count` (quantidade de residuos da imagem anterior). A regra implementada e:
- calcula `current_count` na imagem atual;
- dispara ocorrencia apenas quando `current_count > last_count`.

Essa regra evita gerar eventos repetidos quando a cena permanece estavel, e produz uma deteccao somente em aumento de volume/quantidade detectada.

#### 3.5 Enriquecimento e persistencia da deteccao
Quando a regra de evento e satisfeita, o worker:
- gera imagem anotada e salva em `uploads/<device_id>/labeled/...`;
- monta `image_url` publica (`PUBLIC_BASE_URL + /uploads/...`);
- estima `volume_m3` por heuristica de area de bounding boxes;
- determina tipo dominante de resíduo;
- agrega resumo de infratores detectados;
- insere registro em `detections` com dados de camera, localizacao, confianca e metadados.

Quando ha infratores detectados, tambem insere linhas em `detection_offenders` com `source='ai'`.

#### 3.6 Notificacoes e distribuicao em tempo real
Apos persistir a deteccao, o worker:
- cria notificacoes no banco para usuarios ativos da mesma RPA da camera;
- publica evento `new_detection` no Redis (`notifications:all`).

No frontend, o stream SSE em `/api/v1/notifications/stream` entrega o evento para drawer e toast em tempo real.

#### 3.7 Pos-processamento e organizacao dos arquivos
A imagem original e marcada como processada conforme estrategia configurada:
- `two_folders` (padrao): move para `ocorrencias/` ou `sem_ocorrencia/`;
- `marker` (legado): cria marcador `.jpg.processed`.

Tambem e atualizado `last_capture_at` da camera no banco ao final do ciclo.

#### 3.8 Resiliencia operacional implementada
A pipeline atual inclui mecanismos de robustez:
- retry com backoff exponencial na conexao inicial com PostgreSQL;
- operacao degradada quando Redis estiver indisponivel (sem quebrar persistencia);
- persistencia atomica do estado por dispositivo;
- modo de operacao em idle com `WORKER_ENABLED=false`;
- sincronizacao diaria opcional para Google Drive (quando habilitada por variavel de ambiente).

#### 3.9 Rastreabilidade e validacao tecnica
O projeto inclui script de validacao end-to-end (`test_worker_integration.py`) que verifica:
- upload no ESP32 Server;
- processamento pelo worker;
- criacao de deteccoes com `image_url`;
- criacao de notificacoes;
- publicacao de evento em Redis (bonus).

### Texto complementar sugerido para secao 11 (resultados)
Acrescentar em 11.3:

"No Sprint 4, foi validado o fluxo operacional de tratamento no frontend, incluindo marcacao em analise, resolucao com justificativa e vinculacao de infratores no modal da ocorrencia."

## Observacoes finais
- Manter placeholders de imagem com legenda padronizada (contexto, data da captura e ambiente).
- Separar claramente no texto o que e "entregue no MVP" do que e "recomendacao de evolucao".
- Padronizar termos tecnicos (RPA, SSE, WAHA, PostGIS) em um glossario curto ao final.
