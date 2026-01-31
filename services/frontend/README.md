# Frontend - SAIRA

SPA (Single Page Application) para gestao de ocorrencias de descarte irregular de residuos.

## Stack

- **React 18** + TypeScript
- **Vite 7** (build e dev server)
- **Tailwind CSS 4** (estilizacao)
- **React Router 7** (rotas)
- **Axios** (HTTP client com interceptors JWT)
- **Recharts** (graficos do dashboard)
- **React Leaflet** + Leaflet.heat (mapas interativos e heatmap)
- **Framer Motion** (animacoes)
- **Lucide React** (icones)
- **jsPDF** (exportacao de relatorios em PDF)

## Estrutura

```text
src/
├── main.tsx                    # Entry point (React + AuthProvider)
├── App.tsx                     # Definicao de rotas
│
├── pages/
│   ├── Login.tsx               # Tela de autenticacao
│   ├── Dashboard.tsx           # Painel com KPIs, graficos e mapa de calor
│   ├── Detections.tsx          # Listagem e gestao de ocorrencias
│   └── UsersPage.tsx           # CRUD de usuarios do sistema
│
├── components/
│   ├── Sidebar.tsx             # Barra lateral de navegacao
│   ├── DashboardCharts.tsx     # Graficos (ocorrencias/mes, volume/RPA, reincidencias)
│   ├── OccurrenceModal.tsx     # Modal de detalhes da ocorrencia + exportacao PNG/PDF
│   ├── DeleteModal.tsx         # Modal de confirmacao de exclusao
│   ├── UserModal.tsx           # Modal de criacao/edicao de usuario
│   ├── InputField.tsx          # Campo de input reutilizavel
│   ├── SharedFilters.tsx       # Componente de filtros compartilhados
│   └── Tooltip.tsx             # Tooltip generico
│
├── contexts/
│   └── AuthContext.tsx         # Context de autenticacao (login, logout, token JWT)
│
├── services/
│   ├── api.ts                  # Instancia Axios com interceptors (JWT auto-inject, 401 redirect)
│   └── mockData.ts             # Dados mock para desenvolvimento
│
└── assets/                     # Imagens estaticas
```

## Paginas

### Login (`/`)
Formulario de autenticacao com email/senha. Envia credenciais via `POST /api/v1/auth/login` (OAuth2 password flow) e armazena o token JWT em `localStorage`.

### Dashboard (`/dashboard`)
Painel principal com:
- **KPIs**: total de ocorrencias, volume diario, contagem por status (pendente, em analise, resolvido)
- **Graficos**: ocorrencias por mes, volumetria por RPA, locais reincidentes
- **Mapa de calor**: visualizacao geoespacial das deteccoes via Leaflet + heatmap

### Detections (`/detections`)
Tabela de ocorrencias com filtros por RPA, status, bairro e periodo. Cada linha abre o `OccurrenceModal` com detalhes completos e opcao de exportar como PNG ou PDF.

### Users (`/users`)
CRUD completo de usuarios: listagem, criacao, edicao e exclusao. Campos: nome, email, telefone, secretaria, cargo, RPA.

## Componentes Principais

### OccurrenceModal
Modal de detalhes de uma ocorrencia. Exibe imagem de evidencia, status, localizacao, tipo de residuo, volumetria e infratores. Possui exportacao programatica via **Canvas API** (PNG) e **jsPDF** (PDF), sem dependencia de `html2canvas`.

### AuthContext
Context provider que gerencia o ciclo de autenticacao:
- `login(email, password)`: autentica e salva token + dados do usuario
- `logout()`: limpa localStorage e redireciona para `/`
- `validateToken()`: valida token existente no carregamento da aplicacao
- Interceptor Axios automatico para injetar `Bearer` token e tratar 401

## Desenvolvimento

```bash
# Instalar dependencias
npm install

# Dev server (hot reload)
npm run dev

# Build de producao
npm run build

# Lint
npm run lint
```

## Credenciais de Acesso

O backend ainda nao esta integrado ao frontend. Enquanto isso, o login utiliza credenciais hardcoded em `src/pages/Login.tsx`:

| Email | Senha |
| ----- | ----- |
| `admin@gmail.com` | `12345` |

> **Nota:** quando a integracao com o backend estiver ativa, o login passara a usar o endpoint `POST /api/v1/auth/login` via OAuth2 password flow, e essas credenciais deixarao de funcionar. O usuario padrao do backend e `admin@saira.com` / `admin123`.

## Variaveis de Ambiente

Criar `.env` na raiz do frontend:

```env
VITE_API_URL=http://localhost:8001/api/v1
```

## Docker

O Dockerfile usa multi-stage build:
1. **Stage build**: Node.js compila a aplicacao com Vite
2. **Stage serve**: Nginx serve os arquivos estaticos com configuracao customizada (`nginx.conf`)
