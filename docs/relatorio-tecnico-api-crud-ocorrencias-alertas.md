# Projeto SAÍRA
## Relatório Técnico - API CRUD de Ocorrências e Alertas

---

## SUMÁRIO

1. Visão Executiva
2. Arquitetura do Módulo
   2.1 Stack tecnológica
   2.2 Topologia de serviços
3. Modelos de Dados
   3.1 Detecção (Ocorrência)
   3.2 Câmera
   3.3 Infrator (Offender)
   3.4 Notificação
4. API de Ocorrências (Detecções)
   4.1 Listar ocorrências
   4.2 Busca avançada com filtros
   4.3 Detalhes de uma ocorrência
   4.4 Criar ocorrência
   4.5 Iniciar análise
   4.6 Resolver ocorrência
   4.7 Atualizar e excluir
5. API de Câmeras
6. API de Infratores
   6.1 Cadastro e consulta
   6.2 Vínculos com ocorrências
   6.3 Dashboard analítico de infratores
7. Sistema de Alertas em Tempo Real
   7.1 Fluxo Redis Pub/Sub + SSE
   7.2 Endpoints de notificações
8. Dashboard Analítico
9. Autenticação e Segurança
10. Códigos de Erro e Tratamento

---

## 1. Visão Executiva

O módulo de ocorrências do SAÍRA concentra o ciclo completo de gestão operacional de descarte irregular: captura automatizada, registro da ocorrência, triagem, análise, resolução e comunicação em tempo real para usuários autenticados. A API foi implementada em FastAPI, com persistência em PostgreSQL/PostGIS e integração com Redis para notificações instantâneas via Server-Sent Events (SSE).

O desenho do backend prioriza rastreabilidade e governança do processo. Cada ocorrência mantém histórico de status (`Pendente`, `Em analise`, `Resolvido`) e metadados de auditoria, permitindo medir volume tratado, reincidência por local e efetividade da operação por território (RPA, bairro e logradouro).

Além do CRUD de detecções e câmeras, o módulo inclui o cadastro de perfis de infratores e vínculos por ocorrência, viabilizando indicadores analíticos por tipo de infrator, placa, cor de veículo, volume estimado e reincidência.

---

## 2. Arquitetura do Módulo

### 2.1 Stack tecnológica

| Camada | Tecnologia | Finalidade |
|---|---|---|
| API | FastAPI | Endpoints REST e validação de payload |
| Persistência | PostgreSQL 15 + PostGIS 3.4 | Dados relacionais e geoespaciais |
| ORM | SQLAlchemy 2 (async) | Acesso assíncrono ao banco |
| Migrações | Alembic | Evolução de schema |
| Mensageria em tempo real | Redis Pub/Sub | Distribuição de eventos de notificação |
| Streaming | SSE (`/notifications/stream`) | Atualização em tempo real no frontend |
| Autenticação | JWT (Bearer) | Controle de acesso por usuário |

### 2.2 Topologia de serviços

O backend expõe os endpoints sob o prefixo `/api/v1` e mantém uma separação por domínio: `detections`, `cameras`, `offenders`, `notifications` e `dashboard`. Eventos de nova ocorrência disparam notificações assíncronas, persistidas no banco e publicadas em canal Redis específico por usuário.

Fluxo operacional (resumo):

```text
Ingestão/usuário -> POST /detections -> DB (detections)
                                  -> service de notificações
                                  -> DB (notifications)
                                  -> Redis Pub/Sub
                                  -> GET /notifications/stream (SSE)
                                  -> Frontend atualizado em tempo real
```

---

## 3. Modelos de Dados

### 3.1 Detecção (Ocorrência)

Tabela `detections` com chave UUID e vínculo opcional com `cameras`.

Campos principais:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | Identificador da ocorrência |
| `camera_id` | int | Câmera de origem (opcional) |
| `timestamp` | datetime | Momento da detecção |
| `logradouro`, `bairro`, `rpa` | string | Contexto territorial |
| `latitude`, `longitude`, `geom` | numérico + geoespacial | Posição da ocorrência |
| `waste_type`, `material_type` | string | Classificação do descarte |
| `volume_m3` | decimal | Volume estimado |
| `status` | enum | `Pendente`, `Em analise`, `Resolvido` |
| `image_url` | string | Referência visual da ocorrência |
| `confidence_score` | decimal(0-1) | Confiança da detecção |
| `analysis_started_at`, `analysis_started_by` | datetime/int | Auditoria de início de análise |
| `resolved_at`, `resolved_by` | datetime/int | Auditoria de resolução |
| `resolution_justification`, `forwarded_to_sector` | texto/string | Justificativa e setor de encaminhamento |

### 3.2 Câmera

Tabela `cameras` com chave numérica incremental e suporte geoespacial.

Campos principais:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | int | Identificador da câmera |
| `name`, `device_id` | string | Nome e identificador lógico/físico |
| `logradouro`, `bairro`, `rpa` | string | Localização administrativa |
| `latitude`, `longitude`, `geom` | numérico + geoespacial | Coordenadas |
| `rtsp_url` | string | Fonte de vídeo |
| `capture_interval_seconds` | int | Frequência de captura |
| `is_active` | bool | Disponibilidade operacional |
| `last_capture_at` | datetime | Última captura registrada |

### 3.3 Infrator (Offender)

Modelo em duas tabelas: `offenders` (perfil) e `detection_offenders` (avistamento por ocorrência).

`offenders`:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | Identificador do perfil |
| `name` | string | Nome ou identificação livre |
| `type` | enum | `Carroca`, `Carro`, `Moto`, `Pessoa`, `Outro` |
| `plate`, `vehicle_color` | string | Dados do veículo (quando aplicável) |
| `description` | texto | Observações do perfil |
| `is_active` | bool | Status de uso do perfil |

`detection_offenders`:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | Identificador do vínculo |
| `detection_id` | UUID | Ocorrência associada |
| `offender_id` | UUID | Perfil associado (opcional) |
| `offender_type`, `plate`, `vehicle_color` | enum/string | Snapshot no momento do avistamento |
| `waste_type`, `estimated_volume_m3` | string/decimal | Caracterização do descarte |
| `source` | enum | `manual` ou `ai` |
| `confidence_score` | decimal | Confiança do vínculo automático |
| `notes` | texto | Anotações operacionais |

### 3.4 Notificação

Tabela `notifications`, ligada ao usuário autenticado.

Campos principais:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | Identificador da notificação |
| `user_id` | int | Destinatário |
| `detection_id` | UUID | Ocorrência relacionada (opcional) |
| `type` | enum | `nova_ocorrencia` ou `lote_ocorrencias` |
| `title`, `message` | string/texto | Conteúdo da mensagem |
| `metadata` | JSONB | Dados adicionais |
| `is_read` | bool | Controle de leitura |
| `created_at` | datetime | Carimbo temporal do evento |

---

## 4. API de Ocorrências (Detecções)

Prefixo base: `/api/v1/detections`

### 4.1 Listar ocorrências

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/detections/` | Lista ocorrências com paginação e filtros simples |

Parâmetros de query:

| Parâmetro | Tipo | Obrigatório | Observação |
|---|---|---|---|
| `skip` | int | não | padrão `0` |
| `limit` | int | não | padrão `10`, máximo `100` |
| `rpa` | string | não | filtro territorial |
| `status_filter` | enum | não | status da ocorrência |
| `start_date`, `end_date` | datetime | não | recorte temporal |
| `bairro` | string | não | filtro por bairro |

### 4.2 Busca avançada com filtros

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/detections/search` | Busca paginada com total e filtros compostos |

Parâmetros adicionais relevantes:

| Parâmetro | Tipo | Observação |
|---|---|---|
| `logradouro` | string | busca parcial (`ilike`) |
| `waste_type` | string CSV | aceita aliases normalizados |
| `has_offender` | bool | filtra ocorrências com/sem infrator |
| `volume_min`, `volume_max` | float | faixa de volume |

### 4.3 Detalhes de uma ocorrência

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/detections/{detection_id}` | Retorna payload completo da ocorrência |

### 4.4 Criar ocorrência

| Método | Caminho | Descrição |
|---|---|---|
| `POST` | `/detections/` | Cria ocorrência e dispara pipeline de notificação |

Exemplo de payload:

```json
{
  "camera_id": 12,
  "timestamp": "2026-02-21T12:30:00Z",
  "logradouro": "Av. Caxangá",
  "bairro": "Madalena",
  "rpa": "4",
  "latitude": -8.0476,
  "longitude": -34.9079,
  "waste_type": "entulho",
  "material_type": "construção",
  "volume_m3": 2.4,
  "offenders": null,
  "status": "Pendente",
  "image_url": "https://<CONFIGURAR_NO_ENV>/detections/img-001.jpg",
  "confidence_score": 0.91
}
```

### 4.5 Iniciar análise

| Método | Caminho | Descrição |
|---|---|---|
| `POST` | `/detections/{detection_id}/start-analysis` | Atualiza status para `Em analise` e registra auditoria |

### 4.6 Resolver ocorrência

| Método | Caminho | Descrição |
|---|---|---|
| `POST` | `/detections/{detection_id}/resolve` | Finaliza ocorrência com setor responsável e justificativa |

Payload de resolução:

```json
{
  "resolved_at": "2026-02-21T15:10:00Z",
  "forwarded_to_sector": "Emlurb",
  "resolution_justification": "Equipe de limpeza acionada e ocorrência tratada."
}
```

Fluxo de status documentado:

```text
Pendente -> Em analise -> Resolvido
```

### 4.7 Atualizar e excluir

| Método | Caminho | Descrição |
|---|---|---|
| `PATCH` | `/detections/{detection_id}` | Atualiza campos de classificação e status |
| `DELETE` | `/detections/{detection_id}` | Remove ocorrência |

---

## 5. API de Câmeras

Prefixo base: `/api/v1/cameras`

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/cameras/` | Lista câmeras com paginação e filtros (`rpa`, `is_active`) |
| `GET` | `/cameras/{camera_id}` | Busca câmera por ID |
| `POST` | `/cameras/` | Cadastra nova câmera |
| `PATCH` | `/cameras/{camera_id}` | Atualiza dados da câmera |
| `DELETE` | `/cameras/{camera_id}` | Remove câmera |

Observação técnica: o campo geoespacial `geom` é mantido por trigger no banco com base em latitude/longitude.

---

## 6. API de Infratores

Prefixo base: `/api/v1/offenders`

### 6.1 Cadastro e consulta

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/offenders/` | Lista perfis de infratores com filtros |
| `GET` | `/offenders/{offender_id}` | Detalha perfil |
| `POST` | `/offenders/` | Cria perfil |
| `PATCH` | `/offenders/{offender_id}` | Atualiza perfil |
| `DELETE` | `/offenders/{offender_id}` | Remove perfil |

### 6.2 Vínculos com ocorrências

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/offenders/detections/{detection_id}/offenders` | Lista vínculos de uma ocorrência |
| `POST` | `/offenders/detections/{detection_id}/offenders` | Cria vínculo manual |
| `PATCH` | `/offenders/detection-offenders/{sighting_id}` | Atualiza vínculo |
| `DELETE` | `/offenders/detection-offenders/{sighting_id}` | Remove vínculo |
| `POST` | `/offenders/detections/{detection_id}/offenders/link/{offender_id}` | Vínculo rápido por perfil existente |

### 6.3 Dashboard analítico de infratores

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/offenders/dashboard/offender-stats` | KPIs principais de infratores |
| `GET` | `/offenders/dashboard/offenders-by-type` | Distribuição por tipo |
| `GET` | `/offenders/dashboard/recidivism-by-type` | Recorrência por tipo |
| `GET` | `/offenders/dashboard/offender-volume-by-type` | Volume por tipo |
| `GET` | `/offenders/dashboard/waste-by-offender-type` | Resíduos por tipo |
| `GET` | `/offenders/dashboard/top-plates` | Ranking de placas |
| `GET` | `/offenders/dashboard/vehicle-colors` | Distribuição por cor de veículo |

---

## 7. Sistema de Alertas em Tempo Real

### 7.1 Fluxo Redis Pub/Sub + SSE

Quando uma nova ocorrência é criada, o backend executa um processo assíncrono de notificação. Esse processo persiste mensagens para os usuários-alvo e publica evento em canal Redis por usuário (`notifications:user:{user_id}`). O frontend mantém conexão SSE para receber eventos imediatamente.

```text
Nova detecção -> persistência em notifications -> publish Redis
             -> frontend conectado em /notifications/stream
             -> evento new_detection recebido sem polling
```

### 7.2 Endpoints de notificações

Prefixo base: `/api/v1/notifications`

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/notifications/` | Lista notificações do usuário (`is_read`, `skip`, `limit`) |
| `GET` | `/notifications/summary` | Resumo para pós-login |
| `GET` | `/notifications/stream` | Canal SSE em tempo real |
| `PATCH` | `/notifications/{notification_id}/read` | Marca uma notificação como lida |
| `PATCH` | `/notifications/read-all` | Marca todas como lidas |

---

## 8. Dashboard Analítico

Prefixo base: `/api/v1/dashboard`

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/dashboard/stats` | Totais por status e volume diário |
| `GET` | `/dashboard/occurrences-by-month` | Série mensal (até 12 meses) |
| `GET` | `/dashboard/recurrent-locations` | Top locais reincidentes |
| `GET` | `/dashboard/volume-by-rpa` | Indicadores de volume por RPA |

Esses endpoints consolidam dados para acompanhamento executivo e apoio à decisão operacional em campo.

---

## 9. Autenticação e Segurança

Todas as rotas de operação requerem autenticação `Bearer` via JWT do SAÍRA, com validação de usuário ativo. Pontos de segurança relevantes:

- Controle de acesso por dependência central (`get_current_user`).
- Auditoria de transição de status (`analysis_started_by`, `resolved_by`).
- Tratamento de concorrência e consistência por transações assíncronas.
- Isolamento de segredo por variáveis de ambiente (`SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`).

Exemplo de header:

```http
Authorization: Bearer <JWT_SAIRA>
```

---

## 10. Códigos de Erro e Tratamento

Padrões de retorno:

| Código | Cenário típico |
|---|---|
| `400 Bad Request` | Parâmetros inválidos (ex.: `volume_min > volume_max`) |
| `401 Unauthorized` | Token ausente ou inválido |
| `403 Forbidden` | Usuário inativo ou sem permissão |
| `404 Not Found` | Recurso inexistente (`detection_id`, `offender_id`, `notification_id`) |
| `422 Unprocessable Entity` | Falha de validação de payload |
| `500 Internal Server Error` | Falhas inesperadas de runtime |

Recomendação operacional: monitorar respostas `4xx` recorrentes por endpoint para orientar melhorias de UX/validação no frontend e reduzir retrabalho da equipe de campo.
