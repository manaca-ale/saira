# SPEC: Dashboard de Infratores

## 1. Visao Geral

Implementar o **Dashboard de Infratores** — a segunda aba do Dashboard (atualmente placeholder) — com toda a stack: banco de dados, backend API e frontend.

O sistema deve permitir:
- Visualizacao agregada de infratores detectados (por IA ou input manual)
- Cadastro manual de perfis de infratores conhecidos
- Vinculacao de infratores a ocorrencias (detections)
- Input manual de caracteristicas observadas pelo usuario em cada ocorrencia
- Rastreamento de reincidencia por placa e/ou perfil

---

## 2. Modelo de Dados

### 2.1 Nova tabela: `offenders` (perfis de infratores conhecidos)

Armazena perfis de infratores registrados manualmente pelo usuario (botao "+ Cadastrar Infrator").

| Coluna | Tipo | Restricoes | Descricao |
|--------|------|------------|-----------|
| `id` | UUID | PK, default uuid4 | Identificador unico |
| `name` | VARCHAR(255) | nullable | Nome do infrator (se conhecido) |
| `type` | ENUM OffenderType | NOT NULL | Tipo: `Carroca`, `Carro`, `Moto`, `Pessoa`, `Outro` |
| `plate` | VARCHAR(20) | nullable, unique (quando nao null) | Placa do veiculo |
| `vehicle_color` | VARCHAR(50) | nullable | Cor do veiculo |
| `description` | TEXT | nullable | Descricao livre / observacoes |
| `is_active` | BOOLEAN | default true | Ativo no sistema |
| `created_by` | INTEGER FK -> users.id | SET NULL on delete | Usuario que cadastrou |
| `created_at` | DATETIME | default utcnow | |
| `updated_at` | DATETIME | default utcnow, onupdate | |

**Indices:** `type`, `plate`, `created_by`

### 2.2 Nova tabela: `detection_offenders` (avistamentos por ocorrencia)

Tabela de juncao N:N entre `detections` e `offenders` com dados especificos de cada avistamento. Cada row = um infrator visto em uma ocorrencia especifica.

| Coluna | Tipo | Restricoes | Descricao |
|--------|------|------------|-----------|
| `id` | UUID | PK, default uuid4 | Identificador unico |
| `detection_id` | UUID FK -> detections.id | CASCADE on delete, NOT NULL | Ocorrencia vinculada |
| `offender_id` | UUID FK -> offenders.id | SET NULL on delete, nullable | Perfil do infrator (null = nao vinculado a perfil) |
| `offender_type` | ENUM OffenderType | NOT NULL | Tipo neste avistamento |
| `plate` | VARCHAR(20) | nullable | Placa detectada nesta ocorrencia |
| `vehicle_color` | VARCHAR(50) | nullable | Cor do veiculo observada |
| `waste_type` | VARCHAR(100) | nullable | Tipo de residuo associado a este infrator |
| `estimated_volume_m3` | NUMERIC(10,2) | nullable | Volume estimado descartado por este infrator |
| `source` | ENUM OffenderSource | NOT NULL | `ai` ou `manual` |
| `confidence_score` | NUMERIC(3,2) | nullable | Score de confianca (0-1, somente para source=ai) |
| `created_by` | INTEGER FK -> users.id | SET NULL on delete, nullable | Usuario (null para IA) |
| `notes` | TEXT | nullable | Observacoes do usuario |
| `created_at` | DATETIME | default utcnow | |

**Indices:** `detection_id`, `offender_id`, `plate`, `offender_type`, `source`
**Indice composto:** `(plate, detection_id)` para queries de reincidencia

### 2.3 Enums novos

```python
class OffenderType(str, enum.Enum):
    CARROCA = "Carroca"
    CARRO = "Carro"
    MOTO = "Moto"
    PESSOA = "Pessoa"
    OUTRO = "Outro"

class OffenderSource(str, enum.Enum):
    AI = "ai"
    MANUAL = "manual"
```

### 2.4 Relacionamentos

```
Detection 1 --- N DetectionOffender N --- 1 Offender (opcional)
```

- `Detection.offender_sightings` -> relationship com `DetectionOffender` (cascade delete)
- `Offender.sightings` -> relationship com `DetectionOffender`
- `DetectionOffender.detection` -> relationship com `Detection`
- `DetectionOffender.offender` -> relationship com `Offender`

### 2.5 Migration

Nova migration Alembic: `d5e6f7a8b9c0_add_offenders_tables.py`
- Cria enum `offendertype` e `offendersource` no PostgreSQL
- Cria tabela `offenders`
- Cria tabela `detection_offenders`
- **NAO** altera a coluna existente `detections.offenders` (manter para compatibilidade, deprecar gradualmente)

---

## 3. Backend API

### 3.1 Schemas (Pydantic)

**`schemas/offender.py`**

```python
# --- Offender (perfil) ---
class OffenderCreate:
    name: Optional[str]
    type: OffenderType          # obrigatorio
    plate: Optional[str]
    vehicle_color: Optional[str]
    description: Optional[str]

class OffenderUpdate:
    name: Optional[str]
    type: Optional[OffenderType]
    plate: Optional[str]
    vehicle_color: Optional[str]
    description: Optional[str]
    is_active: Optional[bool]

class OffenderResponse:
    id: UUID
    name, type, plate, vehicle_color, description, is_active
    sighting_count: int         # numero de vezes visto (calculado)
    created_by: Optional[int]
    created_at, updated_at

# --- DetectionOffender (avistamento) ---
class DetectionOffenderCreate:
    detection_id: UUID           # obrigatorio
    offender_id: Optional[UUID]  # vincular a perfil existente
    offender_type: OffenderType  # obrigatorio
    plate: Optional[str]
    vehicle_color: Optional[str]
    waste_type: Optional[str]
    estimated_volume_m3: Optional[Decimal]
    notes: Optional[str]

class DetectionOffenderResponse:
    id: UUID
    detection_id: UUID
    offender_id: Optional[UUID]
    offender_type, plate, vehicle_color, waste_type
    estimated_volume_m3, source, confidence_score
    created_by: Optional[int]
    notes: Optional[str]
    created_at: datetime
    # nested
    offender: Optional[OffenderResponse]  # se vinculado
```

### 3.2 Endpoints

Novo router: `/api/v1/offenders`

#### CRUD de Perfis de Infratores

| Metodo | Rota | Descricao | Auth |
|--------|------|-----------|------|
| `GET` | `/offenders/` | Listar perfis | JWT |
| `GET` | `/offenders/{id}` | Detalhe do perfil (com historico de avistamentos) | JWT |
| `POST` | `/offenders/` | Cadastrar infrator ("+ Cadastrar Infrator") | JWT |
| `PATCH` | `/offenders/{id}` | Atualizar perfil | JWT |
| `DELETE` | `/offenders/{id}` | Remover perfil | JWT |

**Filtros `GET /offenders/`:** `type`, `plate` (busca parcial), `name` (busca parcial), `is_active`, `skip`, `limit`

#### Avistamentos (vinculacao infrator <-> ocorrencia)

| Metodo | Rota | Descricao | Auth |
|--------|------|-----------|------|
| `GET` | `/detections/{id}/offenders` | Listar infratores de uma ocorrencia | JWT |
| `POST` | `/detections/{id}/offenders` | Adicionar infrator a ocorrencia (manual) | JWT |
| `PATCH` | `/detection-offenders/{id}` | Atualizar avistamento | JWT |
| `DELETE` | `/detection-offenders/{id}` | Remover avistamento | JWT |
| `POST` | `/detections/{id}/offenders/link/{offender_id}` | Vincular ocorrencia a perfil existente | JWT |

#### Dashboard de Infratores

| Metodo | Rota | Descricao | Auth |
|--------|------|-----------|------|
| `GET` | `/dashboard/offender-stats` | KPIs agregados | JWT |
| `GET` | `/dashboard/offenders-by-type` | Distribuicao por tipo (donut chart) | JWT |
| `GET` | `/dashboard/recidivism-by-type` | Reincidencia por tipo (bar chart) | JWT |
| `GET` | `/dashboard/offender-volume-by-type` | Volume descartado por tipo (bar chart) | JWT |
| `GET` | `/dashboard/waste-by-offender-type` | Tipo lixo por tipo infrator (stacked bar) | JWT |
| `GET` | `/dashboard/top-plates` | Placas mais reincidentes (tabela) | JWT |
| `GET` | `/dashboard/vehicle-colors` | Distribuicao de cores de veiculos (pie chart) | JWT |

**Filtros comuns para todos endpoints de dashboard:** `start_date`, `end_date`, `status`, `logradouro`, `bairro`, `rpa`

### 3.3 Formato de Resposta dos Endpoints de Dashboard

#### `GET /dashboard/offender-stats`
```json
{
  "total_offenders": 248,
  "recurrent_offenders": 142,
  "high_recurrence": 38,
  "identified_plates": 156,
  "estimated_volume_m3": 2847.0
}
```
- `total_offenders`: COUNT DISTINCT de avistamentos unicos (por plate ou por offender_id; avistamentos sem placa/perfil contam individualmente)
- `recurrent_offenders`: infratores com >1 ocorrencia (agrupados por plate ou offender_id)
- `high_recurrence`: infratores com >=5 ocorrencias (threshold configuravel)
- `identified_plates`: COUNT DISTINCT plates nao-nulas
- `estimated_volume_m3`: SUM de estimated_volume_m3

#### `GET /dashboard/offenders-by-type`
```json
[
  { "type": "Carroca", "count": 87, "percentage": 35.0 },
  { "type": "Carro", "count": 74, "percentage": 30.0 },
  { "type": "Moto", "count": 55, "percentage": 22.0 },
  { "type": "Pessoa", "count": 32, "percentage": 13.0 }
]
```

#### `GET /dashboard/recidivism-by-type`
```json
[
  { "type": "Pessoa", "recurrent_count": 45 },
  { "type": "Carro", "recurrent_count": 38 },
  ...
]
```

#### `GET /dashboard/offender-volume-by-type`
```json
[
  { "type": "Pessoa", "total_volume_m3": 1050.0 },
  { "type": "Carro", "total_volume_m3": 750.0 },
  ...
]
```

#### `GET /dashboard/waste-by-offender-type`
```json
[
  {
    "offender_type": "Pessoa",
    "waste_breakdown": [
      { "waste_type": "Entulho", "count": 30 },
      { "waste_type": "Volumoso", "count": 25 },
      { "waste_type": "Domiciliar", "count": 20 },
      { "waste_type": "Poda", "count": 15 },
      { "waste_type": "Outros", "count": 10 }
    ]
  },
  ...
]
```

#### `GET /dashboard/top-plates`
```json
[
  { "plate": "YZA-8901", "occurrences": 69 },
  { "plate": "VWX-4567", "occurrences": 52 },
  { "plate": "PQR-6789", "occurrences": 45 },
  { "plate": "DEF-9012", "occurrences": 40 },
  { "plate": "XYZ-5678", "occurrences": 37 }
]
```
Parametro `limit` default=5.

#### `GET /dashboard/vehicle-colors`
```json
[
  { "color": "Branco", "count": 87, "percentage": 35.0 },
  { "color": "Preto", "count": 74, "percentage": 30.0 },
  { "color": "Prata", "count": 55, "percentage": 22.0 },
  { "color": "Vermelho", "count": 32, "percentage": 13.0 },
  { "color": "Outros", "count": 32, "percentage": 13.0 }
]
```

---

## 4. Frontend

### 4.1 Nova pagina: Dashboard de Infratores (aba no Dashboard existente)

A aba ja existe como placeholder em [Dashboard.tsx](services/frontend/src/pages/Dashboard.tsx). A implementacao ativa a segunda aba.

#### State management
- `activeTab`: `"ocorrencias" | "infratores"` — controla qual aba esta ativa
- Quando `activeTab === "infratores"`, renderiza o conteudo da nova aba
- Os filtros (Periodo, Status, Logradouro, Bairro, RPA) sao compartilhados entre as abas
- Dados carregados via endpoints de dashboard especificos (server-side aggregation, nao client-side como aba atual)

#### Layout da aba (conforme design)

```
+------------------------------------------------------------------+
| [Filtros: Periodo | Status | Logradouro | Bairro | RPA] [Filter] |
|                                                                    |
| +----------+ +----------+ +----------+ +----------+ +----------+  |
| | Total de | | Infrat.  | | Alta     | | Placas   | | Volume   |  |
| | infrat.  | | reincid. | | reincid. | | identif. | | estimado |  |
| | 248      | | 142      | | 38       | | 156      | | 2.847 m3 |  |
| +----------+ +----------+ +----------+ +----------+ +----------+  |
|                                                                    |
| +--Tipos infrat.--+ +--Reincidencia tipo--+ +--Volume descart.--+ |
| | [Donut Chart]   | | [Bar Chart]         | | [Bar Chart]       | |
| | Carrocas 35%    | | Pessoas, Carros...  | | Pessoas, Carros.. | |
| +-----------------+ +---------------------+ +-------------------+ |
|                                                                    |
| +--Tipo lixo/infr-+ +--Placas reincid.---+ +--Cor veiculos-----+ |
| | [Stacked Bar]   | | YZA-8901   69      | | [Pie Chart]       | |
| | Entulho,Volum.. | | VWX-4567   52      | | Branco 35%        | |
| +-----------------+ +---------------------+ +-------------------+ |
+------------------------------------------------------------------+
```

#### KPI Cards (5)
Cada card tem icone, label com tooltip info, e valor grande.

1. **Total de infratores** — `offender-stats.total_offenders`
2. **Infratores reincidentes** — `offender-stats.recurrent_offenders`
3. **Alta reincidencia** — `offender-stats.high_recurrence`
4. **Placas identificadas** — `offender-stats.identified_plates`
5. **Volume estimado (m3)** — `offender-stats.estimated_volume_m3`

#### Graficos (6 widgets)

| Widget | Tipo Chart | Dados API | Lib |
|--------|-----------|-----------|-----|
| Tipos de infratores | Donut (PieChart) | `/offenders-by-type` | Recharts |
| Reincidencia por tipo | BarChart vertical | `/recidivism-by-type` | Recharts |
| Volume descartado (m3) | BarChart vertical | `/offender-volume-by-type` | Recharts |
| Tipo de lixo por infrator | Stacked BarChart | `/waste-by-offender-type` | Recharts |
| Placas mais reincidentes | Tabela HTML | `/top-plates` | Nativo |
| Cor dos veiculos | PieChart | `/vehicle-colors` | Recharts |

#### Paleta de cores (conforme design)
- Verdes: `#84cc16`, `#a3e635`, `#d9f99d`, `#ecfccb` (escala lime/green)
- Cards: fundo branco, borda `border-gray-100`, `shadow-sm`, `rounded-2xl`
- Badges KPI: icones em circulos com fundo verde claro

### 4.2 Botao "+ Cadastrar Infrator"

Posicao: canto superior direito, ao lado do titulo "Dashboard".

Abre um **modal** (`RegisterOffenderModal`) com o formulario:

| Campo | Tipo Input | Obrigatorio |
|-------|-----------|-------------|
| Nome | text | Nao |
| Tipo de infrator | select (Carroca/Carro/Moto/Pessoa/Outro) | Sim |
| Placa | text (mascara XXX-9999 ou XXX9X99) | Nao |
| Cor do veiculo | select/text | Nao |
| Descricao | textarea | Nao |

Ao salvar: `POST /api/v1/offenders/`

### 4.3 Vinculacao de infrator a ocorrencia (melhoria OccurrenceModal)

Adicionar secao **"Infratores"** no `OccurrenceModal` existente:

- Lista de infratores ja vinculados (vindos de `GET /detections/{id}/offenders`)
- Botao **"+ Adicionar Infrator"** que abre sub-formulario inline ou modal:
  - Opcao 1: **Vincular a perfil existente** — busca por placa/nome (autocomplete, `GET /offenders/?plate=...`)
  - Opcao 2: **Registrar novo avistamento** — formulario:
    - Tipo de infrator (select, obrigatorio)
    - Placa (text, opcional)
    - Cor do veiculo (text/select, opcional)
    - Tipo de residuo (select, opcional)
    - Volume estimado m3 (number, opcional)
    - Observacoes (textarea, opcional)
  - Ao salvar: `POST /detections/{id}/offenders`

### 4.4 Novos services

**`services/offenderService.ts`**
```typescript
// CRUD perfis
getOffenders(filters): Promise<OffenderResponse[]>
getOffender(id): Promise<OffenderResponse>
createOffender(data): Promise<OffenderResponse>
updateOffender(id, data): Promise<OffenderResponse>
deleteOffender(id): Promise<void>

// Avistamentos por detection
getDetectionOffenders(detectionId): Promise<DetectionOffenderResponse[]>
addDetectionOffender(detectionId, data): Promise<DetectionOffenderResponse>
updateDetectionOffender(id, data): Promise<DetectionOffenderResponse>
deleteDetectionOffender(id): Promise<void>
linkOffenderToDetection(detectionId, offenderId): Promise<DetectionOffenderResponse>

// Dashboard
getOffenderStats(filters): Promise<OffenderStats>
getOffendersByType(filters): Promise<OffenderByType[]>
getRecidivismByType(filters): Promise<RecidivismByType[]>
getOffenderVolumeByType(filters): Promise<OffenderVolume[]>
getWasteByOffenderType(filters): Promise<WasteByOffenderType[]>
getTopPlates(filters): Promise<TopPlate[]>
getVehicleColors(filters): Promise<VehicleColor[]>
```

### 4.5 Novos componentes

| Componente | Descricao |
|------------|-----------|
| `OffenderDashboardTab.tsx` | Conteudo completo da aba "Dashboard de Infratores" (KPIs + 6 graficos) |
| `RegisterOffenderModal.tsx` | Modal para cadastro de perfil de infrator |
| `AddDetectionOffenderModal.tsx` | Modal/form para adicionar infrator a uma ocorrencia |
| `OffenderDashboardCharts.tsx` | Componentes de graficos especificos (donut, bars, stacked, pie) |

---

## 5. Logica de Reincidencia

A reincidencia eh calculada agrupando avistamentos (`detection_offenders`) por:
1. **`offender_id`** (quando vinculado a perfil) — mesmo perfil em detections diferentes
2. **`plate`** (quando nao vinculado) — mesma placa em detections diferentes
3. Avistamentos sem `offender_id` e sem `plate` sao contados individualmente (nao geram reincidencia)

**Thresholds:**
- **Reincidente:** aparece em >1 detection distinta
- **Alta reincidencia:** aparece em >=5 detections distintas (configuravel via `settings.HIGH_RECURRENCE_THRESHOLD`, default=5)

**Query SQL conceitual para reincidencia:**
```sql
WITH offender_groups AS (
  SELECT
    COALESCE(offender_id::text, plate, id::text) as group_key,
    COUNT(DISTINCT detection_id) as detection_count
  FROM detection_offenders
  -- joins com detections para filtros de data/local
  GROUP BY group_key
)
SELECT
  COUNT(*) FILTER (WHERE detection_count > 1) as recurrent,
  COUNT(*) FILTER (WHERE detection_count >= 5) as high_recurrence
FROM offender_groups;
```

---

## 6. Fluxo de Input de Dados

### 6.1 Via IA (automatico)
Quando o firmware/pipeline de IA detecta um infrator:
1. `POST /detections/` cria a ocorrencia (como hoje)
2. Pipeline adicional (futuro ou imediato): `POST /detections/{id}/offenders` com `source=ai`, dados extraidos da imagem (tipo, placa se legivel, cor)
3. Sistema tenta auto-match: se placa detectada ja existe em `offenders`, seta `offender_id` automaticamente

### 6.2 Via usuario (manual)
1. Usuario abre `OccurrenceModal` de uma ocorrencia
2. Clica "+ Adicionar Infrator"
3. Preenche dados ou vincula a perfil existente
4. `POST /detections/{id}/offenders` com `source=manual`, `created_by=user_id`

### 6.3 Cadastro de perfil (manual)
1. Usuario clica "+ Cadastrar Infrator" no Dashboard
2. Preenche formulario no modal
3. `POST /offenders/` — cria perfil
4. Perfil fica disponivel para vinculacao futura

---

## 7. Plano de Implementacao (ordem sugerida)

### Fase 1 — Backend (banco + API)
1. Criar models `Offender`, `DetectionOffender` com enums
2. Criar migration Alembic
3. Criar schemas Pydantic
4. Implementar endpoints CRUD de offenders
5. Implementar endpoints de avistamentos (detection_offenders)
6. Implementar endpoints de dashboard (aggregacoes)
7. Registrar routers

### Fase 2 — Frontend Dashboard
8. Criar `offenderService.ts`
9. Criar `OffenderDashboardTab.tsx` com KPIs e graficos
10. Integrar aba no `Dashboard.tsx` (substituir placeholder)
11. Criar `RegisterOffenderModal.tsx`

### Fase 3 — Frontend Vinculacao
12. Criar `AddDetectionOffenderModal.tsx`
13. Atualizar `OccurrenceModal.tsx` com secao de infratores
14. Testes e ajustes

---

## 8. Notas Tecnicas

- **Performance:** Endpoints de dashboard fazem aggregacao server-side via SQL (nao carregam todos registros no frontend como a aba de ocorrencias atual)
- **Filtros:** Os filtros de dashboard de infratores fazem JOIN com `detections` para filtrar por periodo, logradouro, bairro, RPA
- **Compatibilidade:** A coluna existente `detections.offenders` (string) eh mantida mas depreciada. Novos dados vao para `detection_offenders`
- **Paleta:** Usar a mesma escala de verde-lima do design (Tailwind `lime-*`)
- **Charts:** Recharts (ja instalado): PieChart para donuts/pies, BarChart para bars, BarChart com stacked=true para stacked bars
