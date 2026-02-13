# Spec: Sistema de Notificações em Tempo Real

**Data:** 2026-02-13
**Status:** Draft
**Autor:** Claude / Equipe Saira

---

## 1. Visão Geral

Implementar um sistema de notificações que informe os operadores em tempo real sobre novas ocorrências de descarte irregular, mostre o acumulado desde o último login e permita encaminhar alertas via WhatsApp por região (RPA).

### 1.1 Objetivos

| # | Objetivo | Prioridade |
|---|----------|-----------|
| O1 | Notificação em tempo real na tela quando uma nova ocorrência chegar | Alta |
| O2 | Ao fazer login, exibir quantas ocorrências novas desde o último login | Alta |
| O3 | Clicar na notificação navega para Detecções com filtros pré-setados | Alta |
| O4 | Envio de notificações via WhatsApp por RPA da câmera | Média |

---

## 2. Estado Atual (Gaps)

| Componente | Status Atual |
|------------|-------------|
| Real-time (WebSocket/SSE) | Não existe |
| Redis / Message Broker | Não existe no docker-compose |
| Modelo de Notificação no DB | Não existe |
| Campo `last_login` no User | Não existe |
| UI de notificações (sino, badge, drawer) | Não existe |
| Integração WhatsApp | Não existe |

---

## 3. Arquitetura Proposta

```
┌─────────────┐    POST /detections/    ┌──────────────┐
│  ESP-Cam /   │ ────────────────────►  │   FastAPI     │
│  Firmware    │                         │   Backend     │
└─────────────┘                         └──────┬───────┘
                                               │
                              ┌────────────────┼────────────────┐
                              │                │                │
                              ▼                ▼                ▼
                     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                     │  PostgreSQL  │  │    Redis      │  │  WhatsApp    │
                     │  (notific.)  │  │  (pub/sub)    │  │  API Worker  │
                     └──────────────┘  └──────┬───────┘  └──────────────┘
                                              │
                                     SSE / WebSocket
                                              │
                                              ▼
                                     ┌──────────────┐
                                     │   Frontend    │
                                     │  (React SPA)  │
                                     └──────────────┘
```

### 3.1 Escolha: SSE (Server-Sent Events) vs WebSocket

**Recomendação: SSE (Server-Sent Events)**

| Critério | SSE | WebSocket |
|----------|-----|-----------|
| Direção | Unidirecional (server → client) | Bidirecional |
| Complexidade | Baixa | Média |
| Reconexão automática | Nativa (EventSource API) | Manual |
| Necessidade bidirecional? | Não — cliente não envia notificações | Sim |
| Compatibilidade com HTTP/2 | Boa | Requer upgrade |
| Proxy/Load Balancer | Transparente | Requer config especial |

O fluxo é apenas **server → client**, então SSE é mais simples e suficiente. Caso no futuro precise de bidirecionalidade (ex.: chat, ACKs complexos), migrar para WebSocket seria incremental.

### 3.2 Redis como Broker de Eventos

Redis será adicionado ao docker-compose para:
- **Pub/Sub**: quando uma nova detecção é criada, o backend publica no canal `notifications:{rpa}` e `notifications:all`
- **Cache temporário**: manter contagem de notificações não-lidas por usuário (TTL 24h)
- Opcionalmente, rate-limiting para WhatsApp

---

## 4. Modelagem de Dados

### 4.1 Novo Model: `Notification`

```python
# models/notification.py

class NotificationType(str, enum.Enum):
    NOVA_OCORRENCIA = "nova_ocorrencia"
    LOTE_OCORRENCIAS = "lote_ocorrencias"  # batch desde último login

class Notification(Base):
    __tablename__ = "notifications"

    id          = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    detection_id = Column(UUID, ForeignKey("detections.id", ondelete="SET NULL"), nullable=True)
    type        = Column(SQLEnum(NotificationType), nullable=False)
    title       = Column(String(255), nullable=False)
    message     = Column(Text, nullable=False)

    # Metadados para navegação (filtros pré-setados)
    metadata    = Column(JSONB, nullable=True)
    # Ex: {"rpa": "3", "start_date": "2026-02-13T00:00:00", "end_date": "2026-02-13T23:59:59", "status": ["Pendente"]}

    is_read     = Column(Boolean, default=False, index=True)
    created_at  = Column(DateTime, default=func.now())

    # Relacionamentos
    user        = relationship("User", back_populates="notifications")
    detection   = relationship("Detection")
```

### 4.2 Alteração no Model `User`

```python
# Adicionar ao models/user.py

last_login_at = Column(DateTime, nullable=True)

# Relacionamento
notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
```

### 4.3 Nova Tabela: `whatsapp_notification_config`

```python
class WhatsAppNotificationConfig(Base):
    __tablename__ = "whatsapp_notification_configs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    rpa         = Column(String(10), nullable=False, unique=True, index=True)
    phone_number = Column(String(20), nullable=False)    # Número destino no formato +55...
    is_active   = Column(Boolean, default=True)
    min_interval_seconds = Column(Integer, default=300)   # Anti-flood: 5 min entre msgs
    last_sent_at = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=func.now())
    updated_at  = Column(DateTime, default=func.now(), onupdate=func.now())
```

### 4.4 Migration Alembic

Uma nova migration adicionará:
- Tabela `notifications`
- Tabela `whatsapp_notification_configs`
- Coluna `last_login_at` em `users`
- Índice composto em `notifications(user_id, is_read, created_at)`

---

## 5. Backend — Endpoints & Serviços

### 5.1 Novos Endpoints

#### `GET /api/v1/notifications/`
Lista notificações do usuário autenticado.

```
Query params:
  - is_read: bool (opcional)
  - skip: int = 0
  - limit: int = 20

Response: {
  items: Notification[],
  unread_count: int,
  total: int
}
```

#### `GET /api/v1/notifications/stream`
Endpoint SSE. Mantém conexão aberta e envia eventos em tempo real.

```
Event format:
  event: new_detection
  data: {"id": "...", "title": "Nova ocorrência - RPA 3", "message": "Rua X, Bairro Y", "detection_id": "...", "metadata": {...}}
```

#### `PATCH /api/v1/notifications/{id}/read`
Marca uma notificação como lida.

#### `PATCH /api/v1/notifications/read-all`
Marca todas as notificações do usuário como lidas.

#### `GET /api/v1/notifications/summary`
Retorna resumo para o banner de login.

```
Response: {
  unread_count: int,
  since_last_login: int,
  last_login_at: datetime | null,
  by_rpa: { "1": 5, "3": 12, ... }
}
```

#### `POST /api/v1/whatsapp-config/` (admin)
Configura número WhatsApp para um RPA.

#### `GET /api/v1/whatsapp-config/` (admin)
Lista configurações WhatsApp por RPA.

### 5.2 Serviço de Notificações (`services/notification_service.py`)

```python
class NotificationService:

    async def on_new_detection(self, detection: Detection, db: AsyncSession):
        """Chamado após criação de uma nova detecção."""

        # 1. Buscar usuários que devem ser notificados
        #    - Todos os usuários ativos (ou filtrar por RPA do usuário, se aplicável)
        users = await self._get_target_users(detection.rpa, db)

        # 2. Criar notificações no banco (bulk insert)
        notifications = [
            Notification(
                user_id=user.id,
                detection_id=detection.id,
                type=NotificationType.NOVA_OCORRENCIA,
                title=f"Nova ocorrência - RPA {detection.rpa}",
                message=f"{detection.logradouro}, {detection.bairro}",
                metadata={
                    "rpa": detection.rpa,
                    "detection_id": str(detection.id),
                    "bairro": detection.bairro,
                    "start_date": detection.timestamp.isoformat(),
                    "end_date": detection.timestamp.isoformat(),
                }
            )
            for user in users
        ]
        db.add_all(notifications)
        await db.flush()

        # 3. Publicar no Redis para SSE
        await redis.publish(f"notifications:all", json.dumps({...}))
        await redis.publish(f"notifications:rpa:{detection.rpa}", json.dumps({...}))

        # 4. Disparar WhatsApp (se configurado para o RPA)
        await self._maybe_send_whatsapp(detection, db)

    async def get_since_last_login(self, user: User, db: AsyncSession):
        """Retorna contagem de ocorrências desde o último login."""
        if not user.last_login_at:
            return await self._get_recent_count(hours=24, db=db)

        query = select(func.count(Detection.id)).where(
            Detection.timestamp > user.last_login_at
        )
        result = await db.execute(query)
        return result.scalar()
```

### 5.3 SSE Handler (`endpoints/notifications.py`)

```python
from sse_starlette.sse import EventSourceResponse

@router.get("/notifications/stream")
async def notification_stream(
    current_user: User = Depends(get_current_user),
):
    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"notifications:user:{current_user.id}")

        # Heartbeat a cada 30s para manter conexão viva
        try:
            while True:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=30.0
                )
                if message:
                    yield {
                        "event": "new_detection",
                        "data": message["data"]
                    }
                else:
                    yield {"event": "heartbeat", "data": ""}
        finally:
            await pubsub.unsubscribe()

    return EventSourceResponse(event_generator())
```

### 5.4 Hook na Criação de Detecção

Alterar `POST /detections/` para disparar notificações:

```python
# endpoints/detections.py — dentro do create_detection

db.add(new_detection)
await db.commit()
await db.refresh(new_detection)

# >>> Novo: disparar notificações
await notification_service.on_new_detection(new_detection, db)

return new_detection
```

### 5.5 Atualização do Login

```python
# endpoints/auth.py — dentro do login

user.last_login_at = func.now()
await db.commit()
```

---

## 6. Frontend — UI & Componentes

### 6.1 Componentes Novos

#### `NotificationBell` (Sidebar)
- Ícone de sino na Sidebar (entre navegação e avatar/logout)
- Badge vermelho com contagem de não-lidas
- Ao clicar, abre o `NotificationDrawer`

```
┌──────────┐
│  🔔 (12) │  ← Badge com contagem
└──────────┘
```

#### `NotificationDrawer`
- Painel lateral (slide-in da direita) ou dropdown
- Lista de notificações recentes (scroll infinito, max 50)
- Cada item mostra: título, mensagem, tempo relativo ("há 5 min"), ícone de status (lida/não-lida)
- Botão "Marcar todas como lidas"
- **Ao clicar em uma notificação:** navega para `/detections` com query params dos filtros

```
┌─────────────────────────────┐
│  Notificações          ✕    │
│  ─────────────────────────  │
│  ● Nova ocorrência - RPA 3  │
│    Rua X, Boa Vista          │
│    há 5 min                  │
│  ─────────────────────────  │
│  ○ Nova ocorrência - RPA 1  │
│    Av. Y, Cordeiro           │
│    há 32 min                 │
│  ─────────────────────────  │
│  [Marcar todas como lidas]  │
└─────────────────────────────┘
```

#### `LoginNotificationBanner`
- Banner exibido no Dashboard logo após login
- Mostra: "Desde seu último acesso, **X novas ocorrências** foram registradas."
- Botão "Ver ocorrências" → navega para `/detections` com filtro `start_date=last_login_at`
- Dismissível (botão X)
- Desaparece automaticamente após 30 segundos

```
┌──────────────────────────────────────────────────────────────┐
│ ⚠ Desde seu último acesso, 35 novas ocorrências foram       │
│   registradas.                               [Ver ocorrências] ✕ │
└──────────────────────────────────────────────────────────────┘
```

#### `NotificationToast`
- Toast flutuante (canto superior direito) quando chega nova ocorrência em tempo real
- Auto-dismiss após 8 segundos
- Clicável → navega para `/detections?detection_id=...`
- Empilhável (máx. 3 visíveis, as mais antigas saem)

### 6.2 Serviço SSE (`services/notificationService.ts`)

```typescript
class NotificationSSEService {
  private eventSource: EventSource | null = null;
  private listeners: Set<(notification: Notification) => void> = new Set();

  connect(token: string): void {
    this.eventSource = new EventSource(
      `/api/v1/notifications/stream?token=${token}`
    );

    this.eventSource.addEventListener("new_detection", (event) => {
      const notification = JSON.parse(event.data);
      this.listeners.forEach((cb) => cb(notification));
    });

    this.eventSource.onerror = () => {
      // EventSource reconecta automaticamente
      // Mas podemos adicionar backoff customizado se necessário
    };
  }

  disconnect(): void {
    this.eventSource?.close();
    this.eventSource = null;
  }

  subscribe(callback: (notification: Notification) => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }
}

export const notificationSSE = new NotificationSSEService();
```

### 6.3 Context (`contexts/NotificationContext.tsx`)

```typescript
interface NotificationContextType {
  notifications: Notification[];
  unreadCount: number;
  sinceLastLogin: number;
  markAsRead: (id: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  isDrawerOpen: boolean;
  toggleDrawer: () => void;
}
```

- Conecta ao SSE quando o usuário está autenticado
- Busca notificações iniciais + summary via REST ao montar
- Atualiza estado local ao receber evento SSE
- Desconecta do SSE no logout

### 6.4 Navegação com Filtros

Ao clicar em uma notificação, navegar para:

```
/detections?rpa=3&start_date=2026-02-13T10:00:00&end_date=2026-02-13T10:05:00&status=Pendente
```

A página `Detections.tsx` deve:
1. Ler query params no mount (`useSearchParams`)
2. Aplicar os filtros vindos dos query params como estado inicial dos filtros
3. Executar a busca filtrada automaticamente

---

## 7. WhatsApp — Integração

### 7.1 Abordagem

Usar a **API oficial do WhatsApp Business** (Meta Cloud API) com templates de mensagem aprovados.

**Alternativa mais simples para MVP:** Usar a API do **Evolution API** (open source, self-hosted) ou **Z-API** como intermediário.

### 7.2 Fluxo

```
Nova detecção criada
       │
       ▼
NotificationService.on_new_detection()
       │
       ▼
Verifica WhatsAppNotificationConfig para o RPA da câmera
       │
       ├── Não configurado → skip
       │
       ├── Configurado + rate-limit OK →
       │       │
       │       ▼
       │   Envia mensagem via WhatsApp API
       │   Atualiza last_sent_at
       │
       └── Configurado + rate-limit bloqueado → skip (anti-flood)
```

### 7.3 Template da Mensagem WhatsApp

```
🚨 *Alerta SAIRA - Nova Ocorrência*

📍 Local: {logradouro}, {bairro}
🗺️ RPA: {rpa}
📅 Data/Hora: {timestamp}
🗑️ Tipo: {waste_type}
📦 Volume: {volume_m3} m³

🔗 Ver no sistema: {link_detections_page}
```

### 7.4 Serviço WhatsApp (`services/whatsapp_service.py`)

```python
class WhatsAppService:
    def __init__(self):
        self.api_url = settings.WHATSAPP_API_URL
        self.api_token = settings.WHATSAPP_API_TOKEN

    async def send_detection_alert(
        self,
        phone: str,
        detection: Detection
    ) -> bool:
        """Envia alerta de nova detecção via WhatsApp."""
        payload = {
            "phone": phone,
            "message": self._format_message(detection)
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/send-message",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_token}"}
            )
            return response.status_code == 200

    async def should_send(self, config: WhatsAppNotificationConfig) -> bool:
        """Verifica rate-limit (anti-flood)."""
        if not config.is_active:
            return False
        if config.last_sent_at is None:
            return True
        elapsed = (datetime.utcnow() - config.last_sent_at).total_seconds()
        return elapsed >= config.min_interval_seconds
```

### 7.5 Docker-Compose (Opcional: Evolution API self-hosted)

```yaml
evolution-api:
  image: atendai/evolution-api:latest
  ports:
    - "8080:8080"
  environment:
    - AUTHENTICATION_API_KEY=${EVOLUTION_API_KEY}
  volumes:
    - evolution_data:/evolution/data
```

---

## 8. Infraestrutura — Docker-Compose

Adicionar ao `services/docker-compose.yml`:

```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  command: redis-server --appendonly yes
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 3
```

Adicionar ao serviço `backend`:

```yaml
backend:
  environment:
    - REDIS_URL=redis://redis:6379/0
    - WHATSAPP_API_URL=${WHATSAPP_API_URL:-}
    - WHATSAPP_API_TOKEN=${WHATSAPP_API_TOKEN:-}
  depends_on:
    redis:
      condition: service_healthy
```

Dependência Python nova:

```
redis[hiredis]>=5.0.0
sse-starlette>=1.6.0
httpx>=0.25.0   # já deve existir
```

---

## 9. Fases de Implementação

### Fase 1 — Fundação (Backend)
1. Adicionar Redis ao docker-compose
2. Migration: tabela `notifications`, coluna `last_login_at` em `users`
3. Criar model `Notification`
4. Atualizar endpoint de login para gravar `last_login_at`
5. Criar `NotificationService` com `on_new_detection()`
6. Hook no `POST /detections/` para disparar notificações
7. Endpoints REST: listar, marcar lida, marcar todas, summary
8. Endpoint SSE `/notifications/stream`

### Fase 2 — Frontend Core
1. Criar `notificationService.ts` (REST + SSE client)
2. Criar `NotificationContext`
3. Implementar `NotificationBell` na Sidebar
4. Implementar `NotificationDrawer`
5. Implementar `NotificationToast`
6. Implementar `LoginNotificationBanner` no Dashboard
7. Adaptar `Detections.tsx` para aceitar filtros via query params

### Fase 3 — WhatsApp
1. Migration: tabela `whatsapp_notification_configs`
2. Criar `WhatsAppService`
3. Integrar no `NotificationService.on_new_detection()`
4. Endpoints admin para configurar números por RPA
5. (Opcional) Adicionar Evolution API ao docker-compose

### Fase 4 — Polish
1. Configuração de preferências de notificação por usuário (mute por RPA, horários)
2. Página de histórico de notificações
3. Testes E2E do fluxo completo
4. Monitoramento e alertas de falha no envio WhatsApp

---

## 10. Considerações Técnicas

### 10.1 Anti-Rajada (Rate Limiting)

O sistema de câmeras pode gerar rajadas de detecções. Para evitar flood de notificações:

- **Backend:** Agrupar detecções que chegam em janela de 30s em uma única notificação ("X novas ocorrências na região Y")
- **WhatsApp:** `min_interval_seconds` por RPA (default 5 min)
- **Frontend toast:** Máximo 3 toasts simultâneos; se houver mais, mostrar "e mais X notificações"

### 10.2 Escalabilidade SSE

- Cada conexão SSE mantém um worker ocupado. Com 4 workers Uvicorn e poucos operadores (<50), não é problema.
- Se escalar, considerar mover SSE para um serviço separado ou usar WebSocket com Redis adapter.

### 10.3 Limpeza de Notificações

- Cron job ou scheduled task para deletar notificações com mais de 30 dias
- Índice `created_at` na tabela `notifications` para a query de cleanup

### 10.4 Segurança

- SSE endpoint requer autenticação (token via query param já que EventSource não suporta headers custom)
- Validar que o token no query param do SSE é tratado com mesmo nível de segurança do header Authorization
- Não expor números de WhatsApp na API pública (endpoints de config são admin-only)

### 10.5 Offline / Reconexão

- EventSource reconecta automaticamente com backoff nativo do browser
- Ao reconectar, o frontend deve buscar notificações perdidas via REST (`GET /notifications/?is_read=false`)
- Usar `Last-Event-ID` header para reenviar eventos perdidos (se implementar IDs incrementais nos eventos SSE)

---

## 11. Métricas de Sucesso

| Métrica | Target |
|---------|--------|
| Latência notificação (detecção → toast na tela) | < 3 segundos |
| Latência WhatsApp (detecção → msg entregue) | < 30 segundos |
| Uptime SSE | 99.5% |
| Taxa de leitura das notificações | > 70% em 24h |
