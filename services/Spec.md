# Especificação Técnica Tática - Integração Frontend/Backend SAIRA

## 1. Visão Geral
Esta spec detalha a implementação da integração entre o frontend React (Vite) e o backend FastAPI. O objetivo é substituir dados mockados por consumo real de API, implementar autenticação JWT robusta, configurar mapas interativos (Leaflet) e preparar o ambiente de desenvolvimento com dados de teste (seeding).

---

## 2. Arquivos a Criar

### **Backend**

#### `services/backend/seed_db.py`
* **Objetivo:** Script standalone para popular o banco de dados com dados fictícios para desenvolvimento.
* **Ações:**
    * Importar `Faker` e modelos SQLAlchemy (`User`, `Camera`, `Detection`).
    * Criar função `seed()`:
        * Limpar tabelas existentes (opcional, ou verificar se admin já existe).
        * **Usuários:** Criar 1 Admin fixo (email: `admin@saira.com`, senha conhecida) e 5 usuários aleatórios.
        * **Câmeras:** Criar 3-5 câmeras com coordenadas reais de Recife ou Vitória (ex: -20.3155, -40.3128) para visualização válida no mapa.
        * **Detecções:** Gerar 20+ detecções vinculadas às câmeras criadas, variando status e timestamps.
    * Executar commit ao final.

### **Frontend**

#### `services/frontend/src/services/api.ts`
* **Objetivo:** Centralizar configuração do Axios.
* **Ações:**
    * Criar instância `axios.create` com `baseURL` apontando para a API (ex: `http://localhost:8000/api/v1`).
    * **Interceptor de Request:** Ler token do `localStorage` (chave `@Saira:token`) e injetar no header `Authorization: Bearer <token>`.
    * **Interceptor de Response (Opcional):** Tratar erro 401 (Unauthorized) para deslogar usuário automaticamente.

#### `services/frontend/src/contexts/AuthContext.tsx`
* **Objetivo:** Gerenciar estado global de autenticação.
* **Ações:**
    * Criar Contexto e Provider.
    * **Estado:** `user` (dados do usuário), `isAuthenticated` (boolean), `loading` (boolean).
    * **Função `signIn({ email, password })`:**
        * Chamar endpoint `POST /auth/login`.
        * Salvar token no `localStorage`.
        * Atualizar header do axios e estado do usuário.
    * **Função `signOut()`:** Remover token e limpar estado.
    * **Effect:** Ao carregar, verificar se existe token no storage e validar/recuperar dados do usuário (`GET /auth/me`).

---

## 3. Arquivos a Modificar

### **Backend**

#### `services/backend/app/main.py`
* **O que fazer:** Configurar CORS.
* **Detalhes:**
    * Importar `CORSMiddleware`.
    * Adicionar middleware permitindo origens do frontend (`http://localhost:5173`, `http://localhost:3000`).
    * Permitir métodos `*` e headers `*` (essencial para Authorization header).

#### `services/backend/app/api/v1/endpoints/users.py`
* **O que fazer:** Ajustar filtro de listagem.
* **Detalhes:** Garantir que o endpoint `GET /` aceite query param `q` ou `search` para filtrar usuários por nome/email (usado na barra de busca do frontend).

---

### **Frontend - Autenticação & Core**

#### `services/frontend/src/pages/Login.tsx`
* **O que fazer:** Integrar lógica real.
* **Detalhes:**
    * Substituir validação fixa (`if email === ...`) pela chamada `signIn()` do `AuthContext`.
    * Tratar erros (try/catch) e exibir feedback visual (ex: "Credenciais inválidas").
    * Adicionar links visuais para "Esqueci minha senha" e "Solicitar cadastro" (podem ser links mailto ou modais simples por enquanto).

#### `services/frontend/src/components/InputField.tsx`
* **O que fazer:** Adicionar funcionalidade "Show Password".
* **Detalhes:**
    * Adicionar prop opcional `isPassword`.
    * Se `isPassword` for true, renderizar ícone de "olho" (Eye/EyeOff do Lucide).
    * Alternar atributo `type` do input entre `password` e `text` ao clicar no ícone.

#### `services/frontend/src/components/Sidebar.tsx`
* **O que fazer:** Melhorias de UX.
* **Detalhes:**
    * Atualizar ícone do item "Mapa" para `Camera`.
    * No botão de "Sair", adicionar confirmação (`window.confirm` ou modal customizado) antes de chamar `signOut`.

---

### **Frontend - Funcionalidades**

#### `services/frontend/src/pages/Dashboard.tsx`
* **O que fazer:** Consumir KPIs reais.
* **Detalhes:**
    * Criar estado local `stats` para armazenar os contadores.
    * Usar `useEffect` para buscar dados em `GET /dashboard/stats`.
    * Adicionar `Tooltip` nos ícones de informação dos Cards para explicar métricas (ex: "Total acumulado no mês").

#### `services/frontend/src/components/DashboardCharts.tsx`
* **O que fazer:** Implementar Mapa Interativo.
* **Detalhes:**
    * Substituir placeholder visual por componentes do `react-leaflet`.
    * **Snippet Base:**
        ```tsx
        <MapContainer center={initialCoords} zoom={13} ...>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {cameras.map(cam => (
            <Marker position={[cam.lat, cam.lng]}>
              <Popup>{cam.name}</Popup>
            </Marker>
          ))}
        </MapContainer>
        ```
    * Iterar sobre lista de ocorrências/câmeras reais passadas via props.

#### `services/frontend/src/pages/Detections.tsx`
* **O que fazer:** Listagem Real e Mapa Modal.
* **Detalhes:**
    * **Tabela:** Fetch em `GET /detections`. Mapear colunas corretamente.
    * **Filtros:** Input de texto para Logradouro (com debounce).
    * **Modal de Mapa:** Adicionar botão na linha da tabela ("Ver no Mapa"). Ao clicar, abrir Modal contendo um `MapContainer` centralizado exatamente na `lat/lon` daquela ocorrência.
    * **UI:** Aplicar estilo zebrado nas linhas (`even:bg-gray-50`) para facilitar leitura.

#### `services/frontend/src/pages/UsersPage.tsx`
* **O que fazer:** CRUD Completo.
* **Detalhes:**
    * Listagem: `GET /users`.
    * Criação: `POST /users` (via UserModal).
    * Edição: `PATCH /users/:id` (via UserModal com dados preenchidos).
    * Exclusão: `DELETE /users/:id`.
    * **UX:** Exibir Toast de sucesso apenas após confirmação da API (status 200/204).

---

# ✅ STATUS DA IMPLEMENTAÇÃO

## 🎉 IMPLEMENTAÇÃO 100% CONCLUÍDA

**Data**: 25 de Janeiro de 2026
**Status**: Todos os requisitos implementados e testados com sucesso.

### ✅ Recursos Implementados

#### Backend
- ✅ Script de seeding (`seed_db.py`) com dados realistas brasileiros
- ✅ CORS configurado para permitir frontend
- ✅ Endpoint de usuários com filtros de busca
- ✅ Autenticação JWT funcionando
- ✅ PostgreSQL + PostGIS integrado
- ✅ 6 usuários criados (1 admin + 5 aleatórios)
- ✅ 5 câmeras em Recife com coordenadas reais
- ✅ 25+ detecções geradas

#### Frontend
- ✅ Serviço API (`api.ts`) com interceptors JWT
- ✅ AuthContext com gerenciamento global de autenticação
- ✅ Login integrado com API real
- ✅ InputField com show/hide password
- ✅ Sidebar com confirmação de logout e ícone correto
- ✅ Dashboard consumindo KPIs reais da API
- ✅ Mapa Leaflet implementado com câmeras
- ✅ Detecções com listagem real, filtros e modal de mapa
- ✅ CRUD completo de usuários com Toast

### 🔧 Correções Realizadas

1. **NumPy Compatibility** - Adicionado `numpy<2.0.0` para compatibilidade com shapely/geoalchemy2
2. **TypeScript Imports** - Corrigido import de ReactNode para `import type`
3. **Email Validation** - Adicionado `email-validator` para Pydantic
4. **Docker Compose** - Removido atributo deprecated `version`
5. **Port Configuration** - Alinhado porta 8001 em todos os arquivos
6. **Alembic Setup** - Configurado para ignorar schemas PostGIS
7. **Database Creation** - Tabelas criadas via SQLAlchemy

### 🌐 URLs de Acesso

| Serviço | URL | Credenciais |
|---------|-----|-------------|
| **Frontend** | http://localhost:3000 | - |
| **Backend API** | http://localhost:8001/docs | - |
| **Login** | http://localhost:3000 | admin@saira.com / admin123 |
| **pgAdmin** | http://localhost:5050 | admin@saira.com / admin |

### 📊 Dados Disponíveis

- **Usuários**: 6 (1 admin + 5 usuários de teste)
- **Câmeras**: 5 (Boa Viagem, Derby, Casa Forte, Recife Antigo, Piedade)
- **Detecções**: 25+ (com tipos variados e timestamps dos últimos 30 dias)

### 🎯 Testes Realizados

- ✅ Login funcional com JWT
- ✅ Dashboard carregando dados reais
- ✅ Mapa exibindo câmeras corretamente
- ✅ Detecções listando e filtrando
- ✅ Modal de mapa nas detecções funcionando
- ✅ CRUD de usuários completo
- ✅ Logout com limpeza de sessão
- ✅ Interceptors JWT funcionando
- ✅ Redirecionamento automático em 401

### 🚀 Como Executar

```bash
cd c:\saira\services

# 1. Parar containers anteriores
docker-compose down -v

# 2. Iniciar containers
docker-compose up -d --build

# 3. Aguardar 30 segundos

# 4. Criar tabelas (se necessário)
docker-compose exec backend python -c "
import asyncio
from app.core.database import engine, Base
from app.models import User, Camera, Detection
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
asyncio.run(create_tables())
"

# 5. Popular banco de dados
docker-compose exec backend python seed_db.py

# 6. Acessar: http://localhost:3000
```

### 📝 Documentação Adicional

- [EXECUTAR_AGORA_ATUALIZADO.md](./EXECUTAR_AGORA_ATUALIZADO.md) - Guia completo de execução
- [CORRECAO_APLICADA.md](./CORRECAO_APLICADA.md) - Detalhes das correções
- [RESUMO_CORRECOES.md](./RESUMO_CORRECOES.md) - Resumo de todas as correções

---

**Sistema SAIRA implementado com sucesso!** 🎉🗺️