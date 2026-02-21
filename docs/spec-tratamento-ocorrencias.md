# SPEC: Tratamento de Ocorrencias na Tela de Detections

## Resumo

Implementar o fluxo completo de tratamento de ocorrencias na tela "Detecoes de cameras", incluindo acoes inline na tabela para alterar status ("Marcar como resolvido", "Marcar em analise") e um modal de confirmacao com campos obrigatorios (data de resolucao, setor encaminhado, justificativa).

---

## Estado Atual

### Frontend
- **Pagina:** `services/frontend/src/pages/Detections.tsx`
- **Modal de visualizacao:** `services/frontend/src/components/OccurrenceModal.tsx`
- **Service:** `services/frontend/src/services/detectionService.ts`
- Status exibidos: `Pendente`, `Em analise`, `Resolvido` (apenas visual, sem acoes)
- Coluna "Acao" possui apenas o botao de visualizar (icone Eye)
- `OccurrenceModal` mostra informacoes + export PNG/PDF, sem acoes de tratamento
- Existe `updateDetectionStatus()` no service mas nao e usada na UI

### Backend
- **Endpoint PATCH:** `services/backend/app/api/v1/endpoints/detections.py` — `PATCH /{detection_id}`
- **Model:** `services/backend/app/models/detection.py` — enum `DetectionStatus` (PENDENTE, EM_ANALISE, RESOLVIDO)
- **Schema:** `services/backend/app/schemas/detection.py` — `DetectionUpdate` aceita `status`, `offenders`, `waste_type`, `material_type`, `volume_m3`
- Nao existem campos para `resolved_at`, `resolved_by`, `justification`, `forwarded_to_sector`

### Banco de Dados
- Tabela `detections` nao possui colunas de resolucao/tratamento
- Enum `detectionstatus` com valores: `PENDENTE`, `EM_ANALISE`, `RESOLVIDO`

---

## Telas do Figma (Referencia)

### Tela 1 — Listagem de ocorrencias
- Tabela com colunas: ID, Logradouro, Bairro, RPA, Data e Hora, Tipo de residuo, Volumetria, Infratores, Status, Acao
- Coluna **Status** mostra badges coloridos: `Pendente` (vermelho), `Em analise` (amarelo/laranja), `Resolvido` (verde)
- Coluna **Acao** possui 3 botoes:
  1. **Visualizar** (icone olho) — abre modal de detalhes
  2. **Marcar como resolvido** (icone check-circle) — abre modal de confirmacao de resolucao
  3. **Marcar em analise** (icone relogio/analise) — altera status diretamente para "Em analise"
- Filtros: Periodo, Status, Logradouro, Bairro, RPA
- Botao de download CSV

### Tela 2 — Modal "Visualizar ocorrencia"
- Exibe: imagens da evidencia, Status, ID, Data e Hora, Logradouro, Bairro, RPA, Latitude, Longitude, Tipo de residuo, Tipo de material, Volumetria aprox., Infratores
- Footer com botoes:
  1. Download (export PNG/PDF) — ja existente
  2. "Ver localizacao no mapa" — abre mapa com pin
  3. "Marcar como resolvido" (icone check-circle) — abre modal de confirmacao

### Tela 3 — Modal "Marcar como resolvido"
- Titulo: "Voce tem certeza que deseja marcar essa ocorrencia como resolvida?"
- Subtitulo: "Essa acao nao podera ser desfeita ao ser confirmada."
- Campos obrigatorios:
  1. **Data** (date picker) — "Data de resolucao da ocorrencia" (obrigatorio)
  2. **Enviado para algum setor?** (select/dropdown) — opcoes de setores (obrigatorio)
  3. **Justificativa** (textarea) — max 400 caracteres (obrigatorio)
- Botoes: "Cancelar" (vermelho, outline) | "Salvar" (verde, filled)

---

## Alteracoes Necessarias

### 1. Migracao de Banco de Dados

**Nova migration Alembic:** Adicionar colunas a tabela `detections`:

```sql
ALTER TABLE detections ADD COLUMN resolved_at TIMESTAMP;
ALTER TABLE detections ADD COLUMN resolved_by INTEGER REFERENCES users(id);
ALTER TABLE detections ADD COLUMN resolution_justification TEXT;
ALTER TABLE detections ADD COLUMN forwarded_to_sector VARCHAR(100);
ALTER TABLE detections ADD COLUMN analysis_started_at TIMESTAMP;
ALTER TABLE detections ADD COLUMN analysis_started_by INTEGER REFERENCES users(id);
```

**Arquivo:** `services/backend/alembic/versions/xxxx_add_occurrence_treatment_fields.py`

Colunas novas:
| Coluna | Tipo | Nullable | Descricao |
|---|---|---|---|
| `resolved_at` | `DateTime` | sim | Data/hora da resolucao informada pelo usuario |
| `resolved_by` | `Integer FK(users.id)` | sim | Usuario que marcou como resolvido |
| `resolution_justification` | `Text` | sim | Justificativa da resolucao (max 400 chars via schema) |
| `forwarded_to_sector` | `String(100)` | sim | Setor para o qual foi encaminhada |
| `analysis_started_at` | `DateTime` | sim | Data/hora em que entrou "Em analise" |
| `analysis_started_by` | `Integer FK(users.id)` | sim | Usuario que marcou como "Em analise" |

---

### 2. Backend — Model

**Arquivo:** `services/backend/app/models/detection.py`

Adicionar ao model `Detection`:
```python
resolved_at = Column(DateTime, nullable=True)
resolved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
resolution_justification = Column(Text, nullable=True)
forwarded_to_sector = Column(String(100), nullable=True)
analysis_started_at = Column(DateTime, nullable=True)
analysis_started_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
```

---

### 3. Backend — Schemas

**Arquivo:** `services/backend/app/schemas/detection.py`

#### Novo schema `DetectionResolve`:
```python
class DetectionResolve(BaseModel):
    resolved_at: datetime
    forwarded_to_sector: str = Field(..., max_length=100)
    resolution_justification: str = Field(..., max_length=400)
```

#### Novo schema `DetectionStartAnalysis`:
```python
class DetectionStartAnalysis(BaseModel):
    pass  # Nenhum campo adicional necessario; o backend registra timestamp e usuario
```

#### Atualizar `DetectionResponse`:
Adicionar os novos campos ao response:
```python
resolved_at: Optional[datetime] = None
resolved_by: Optional[int] = None
resolution_justification: Optional[str] = None
forwarded_to_sector: Optional[str] = None
analysis_started_at: Optional[datetime] = None
analysis_started_by: Optional[int] = None
```

---

### 4. Backend — Endpoints

**Arquivo:** `services/backend/app/api/v1/endpoints/detections.py`

#### Novo endpoint `POST /detections/{detection_id}/resolve`:
- Valida que status atual != `RESOLVIDO`
- Recebe body `DetectionResolve`
- Seta `status = RESOLVIDO`, `resolved_at`, `resolved_by = current_user.id`, `resolution_justification`, `forwarded_to_sector`
- Retorna `DetectionResponse`

#### Novo endpoint `POST /detections/{detection_id}/start-analysis`:
- Valida que status atual == `PENDENTE`
- Seta `status = EM_ANALISE`, `analysis_started_at = now()`, `analysis_started_by = current_user.id`
- Retorna `DetectionResponse`

#### Lista de setores (opcional como endpoint ou constante):
Criar constante ou endpoint `GET /sectors` retornando a lista de setores disponiveis. Sugestao inicial de setores:
- "Emlurb"
- "Secretaria de Meio Ambiente"
- "Secretaria de Infraestrutura"
- "Defesa Civil"
- "Outro"

> **Nota:** Se a lista de setores for fixa, pode ser uma constante no frontend. Se for dinamica, criar tabela `sectors` e endpoint.

---

### 5. Frontend — Service

**Arquivo:** `services/frontend/src/services/detectionService.ts`

#### Nova funcao `resolveDetection`:
```typescript
export async function resolveDetection(
  id: string,
  data: {
    resolved_at: string;        // ISO datetime
    forwarded_to_sector: string;
    resolution_justification: string;
  }
): Promise<Detection> {
  const response = await api.post(`/detections/${id}/resolve`, data);
  return response.data;
}
```

#### Nova funcao `startAnalysis`:
```typescript
export async function startAnalysis(id: string): Promise<Detection> {
  const response = await api.post(`/detections/${id}/start-analysis`);
  return response.data;
}
```

---

### 6. Frontend — Componente `ResolveConfirmationModal`

**Novo arquivo:** `services/frontend/src/components/ResolveConfirmationModal.tsx`

Props:
```typescript
interface ResolveConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (data: {
    resolved_at: string;
    forwarded_to_sector: string;
    resolution_justification: string;
  }) => void;
  isLoading: boolean;
}
```

Conteudo:
- Titulo: "Voce tem certeza que deseja marcar essa ocorrencia como resolvida?"
- Subtitulo: "Essa acao nao podera ser desfeita ao ser confirmada."
- Campo **Data** (`<input type="date">`): label "Data*", placeholder "Data de resolucao da ocorrencia" — obrigatorio
- Campo **Enviado para algum setor?** (`<select>`): label "Enviado para algum setor?*", placeholder "Selecione" — obrigatorio
  - Opcoes: "Emlurb", "Secretaria de Meio Ambiente", "Secretaria de Infraestrutura", "Defesa Civil", "Outro"
- Campo **Justificativa** (`<textarea>`): label "Justificativa *", placeholder "Insira a justificativa", maxLength=400, contador "0/400 caracteres" — obrigatorio
- Botao "Cancelar": vermelho/outline, chama `onClose`
- Botao "Salvar": verde/filled, desabilitado ate todos os campos estarem preenchidos, chama `onConfirm`
- Validacao: todos os 3 campos sao obrigatorios. Botao "Salvar" fica disabled se algum estiver vazio

---

### 7. Frontend — Componente `AnalysisConfirmationModal`

**Novo arquivo:** `services/frontend/src/components/AnalysisConfirmationModal.tsx`

Props:
```typescript
interface AnalysisConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  isLoading: boolean;
}
```

Conteudo:
- Titulo: "Voce tem certeza que deseja marcar essa ocorrencia como em analise?"
- Subtitulo: "A ocorrencia sera movida para o status 'Em analise'."
- Botao "Cancelar": outline, chama `onClose`
- Botao "Confirmar": verde/filled, chama `onConfirm`

---

### 8. Frontend — Alteracoes na Pagina `Detections.tsx`

**Arquivo:** `services/frontend/src/pages/Detections.tsx`

#### Novos estados:
```typescript
const [resolveTarget, setResolveTarget] = useState<Detection | null>(null);
const [analysisTarget, setAnalysisTarget] = useState<Detection | null>(null);
const [isResolving, setIsResolving] = useState(false);
const [isStartingAnalysis, setIsStartingAnalysis] = useState(false);
```

#### Coluna "Acao" — Adicionar botoes:
Na celula de acao de cada linha (alem do botao Eye existente), adicionar:

1. **Botao "Marcar em analise"** (icone `Clock` ou `Search`):
   - Visivel apenas quando `status === "Pendente"`
   - onClick: `setAnalysisTarget(row)`

2. **Botao "Marcar como resolvido"** (icone `CheckCircle`):
   - Visivel quando `status === "Pendente"` ou `status === "Em analise"`
   - onClick: `setResolveTarget(row)`

#### Handler `handleResolve`:
```typescript
const handleResolve = async (data: { resolved_at: string; forwarded_to_sector: string; resolution_justification: string }) => {
  if (!resolveTarget) return;
  setIsResolving(true);
  try {
    await resolveDetection(resolveTarget.id, data);
    // Atualizar o status localmente no array detections
    setDetections(prev => prev.map(d =>
      d.id === resolveTarget.id ? { ...d, status: "Resolvido" as const } : d
    ));
    setResolveTarget(null);
  } catch (e) {
    console.error("Erro ao resolver:", e);
    // TODO: Exibir toast de erro
  } finally {
    setIsResolving(false);
  }
};
```

#### Handler `handleStartAnalysis`:
```typescript
const handleStartAnalysis = async () => {
  if (!analysisTarget) return;
  setIsStartingAnalysis(true);
  try {
    await startAnalysis(analysisTarget.id);
    setDetections(prev => prev.map(d =>
      d.id === analysisTarget.id ? { ...d, status: "Em analise" as const } : d
    ));
    setAnalysisTarget(null);
  } catch (e) {
    console.error("Erro ao iniciar analise:", e);
  } finally {
    setIsStartingAnalysis(false);
  }
};
```

#### Renderizar modais no final do JSX:
```tsx
{resolveTarget && (
  <ResolveConfirmationModal
    isOpen={!!resolveTarget}
    onClose={() => setResolveTarget(null)}
    onConfirm={handleResolve}
    isLoading={isResolving}
  />
)}
{analysisTarget && (
  <AnalysisConfirmationModal
    isOpen={!!analysisTarget}
    onClose={() => setAnalysisTarget(null)}
    onConfirm={handleStartAnalysis}
    isLoading={isStartingAnalysis}
  />
)}
```

---

### 9. Frontend — Alteracoes no `OccurrenceModal.tsx`

**Arquivo:** `services/frontend/src/components/OccurrenceModal.tsx`

#### Novas props:
```typescript
interface OccurrenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: any;
  onResolve?: () => void;   // Callback para abrir modal de resolucao
  onMapView?: () => void;   // Callback para "Ver localizacao no mapa"
}
```

#### Adicionar no footer (ao lado do botao de Download):
1. **Botao "Ver localizacao no mapa"**: texto + icone MapPin, abre link do Google Maps com lat/lng
2. **Botao "Marcar como resolvido"** (icone `CheckCircle`):
   - Visivel quando `data.status !== "Resolvido"`
   - Tooltip: "Marcar como resolvido"
   - onClick: chama `onResolve()` que fecha o OccurrenceModal e abre o ResolveConfirmationModal

#### Exibir campo "Tipo de material":
- Adicionar na grid de informacoes o campo `material_type` / "Tipo de material" (visivel no Figma: "Lixo domiciliar" + "Plastico")

---

## Fluxo de Interacao

### Fluxo 1 — Marcar como "Em analise" (via tabela)
1. Usuario clica no icone de analise na coluna Acao (visivel apenas em ocorrencias `Pendente`)
2. Abre `AnalysisConfirmationModal` com confirmacao simples
3. Usuario confirma
4. `POST /detections/{id}/start-analysis`
5. Status atualiza para "Em analise" na tabela (badge amarelo)

### Fluxo 2 — Marcar como "Resolvido" (via tabela)
1. Usuario clica no icone check-circle na coluna Acao (visivel em `Pendente` ou `Em analise`)
2. Abre `ResolveConfirmationModal`
3. Usuario preenche: Data de resolucao, Setor, Justificativa
4. Clica "Salvar"
5. `POST /detections/{id}/resolve`
6. Status atualiza para "Resolvido" na tabela (badge verde)

### Fluxo 3 — Marcar como "Resolvido" (via modal de detalhes)
1. Usuario clica no icone Eye para visualizar a ocorrencia
2. No `OccurrenceModal`, clica em "Marcar como resolvido"
3. `OccurrenceModal` fecha, `ResolveConfirmationModal` abre
4. Mesmo fluxo do Fluxo 2 a partir do passo 3

---

## Regras de Negocio

1. **Transicoes de status validas:**
   - `Pendente` -> `Em analise`
   - `Pendente` -> `Resolvido`
   - `Em analise` -> `Resolvido`
   - Nao e possivel voltar de `Resolvido` para outro status
   - Nao e possivel voltar de `Em analise` para `Pendente`

2. **Campos obrigatorios para resolucao:** `resolved_at`, `forwarded_to_sector`, `resolution_justification`

3. **Validacao de justificativa:** maximo 400 caracteres

4. **Visibilidade dos botoes de acao na tabela:**
   - `Pendente`: exibe Eye + Clock (analise) + CheckCircle (resolver)
   - `Em analise`: exibe Eye + CheckCircle (resolver)
   - `Resolvido`: exibe apenas Eye

5. **Atualizacao otimista:** Apos chamada bem-sucedida a API, atualizar o estado local sem recarregar a lista toda

---

## Arquivos Impactados

| Arquivo | Tipo de Alteracao |
|---|---|
| `services/backend/alembic/versions/xxxx_add_occurrence_treatment_fields.py` | **Novo** — Migracao |
| `services/backend/app/models/detection.py` | **Editar** — Adicionar colunas |
| `services/backend/app/schemas/detection.py` | **Editar** — Novos schemas + campos no response |
| `services/backend/app/api/v1/endpoints/detections.py` | **Editar** — Novos endpoints resolve/start-analysis |
| `services/frontend/src/services/detectionService.ts` | **Editar** — Novas funcoes API |
| `services/frontend/src/components/ResolveConfirmationModal.tsx` | **Novo** — Modal de confirmacao de resolucao |
| `services/frontend/src/components/AnalysisConfirmationModal.tsx` | **Novo** — Modal de confirmacao de analise |
| `services/frontend/src/pages/Detections.tsx` | **Editar** — Botoes de acao + handlers + modais |
| `services/frontend/src/components/OccurrenceModal.tsx` | **Editar** — Botoes footer + tipo material |

---

## Dependencias de Implementacao (Ordem Sugerida)

1. Migracao do banco (novas colunas)
2. Backend: model + schemas + endpoints
3. Frontend: service (novas funcoes API)
4. Frontend: `ResolveConfirmationModal` (novo componente)
5. Frontend: `AnalysisConfirmationModal` (novo componente)
6. Frontend: `Detections.tsx` (botoes de acao + handlers + integracao dos modais)
7. Frontend: `OccurrenceModal.tsx` (botoes footer + campo tipo material)

---

## Fora de Escopo (para futuras iteracoes)

- Historico/log de alteracoes de status (audit trail)
- Notificacoes ao mudar status
- Permissoes por role (qualquer usuario autenticado pode alterar status)
- Tabela dedicada de `sectors` com CRUD
- "Ver localizacao no mapa" como mapa embarcado (por ora, link externo Google Maps)
