# 🚀 Instruções de Execução - SAIRA

## ⚠️ IMPORTANTE - Leia antes de executar

Este guia contém todos os passos necessários para rodar o projeto SAIRA com Docker.

## 📋 Pré-requisitos

- Docker instalado e rodando
- Docker Compose instalado
- Portas livres: **3000** (frontend), **8001** (backend), **5432** (postgres), **5050** (pgadmin)

## 🔧 Passo 1: Preparar o ambiente

```bash
# Navegar para o diretório services
cd c:\saira\services

# Verificar se os arquivos .env existem
# Frontend
ls frontend/.env

# Backend
ls backend/.env

# Se não existirem, serão criados automaticamente pelo Docker
```

## 🐳 Passo 2: Parar containers existentes (se houver)

```bash
# Parar e remover containers antigos
docker-compose down -v

# Limpar imagens antigas (opcional)
docker-compose down --rmi all -v
```

## 🏗️ Passo 3: Construir e iniciar os containers

```bash
# Construir e iniciar TODOS os serviços
docker-compose up -d --build

# Aguardar cerca de 2-3 minutos para todos os serviços iniciarem
# Você pode monitorar o progresso com:
docker-compose logs -f
```

## 📊 Passo 4: Verificar se os serviços estão rodando

```bash
# Verificar status dos containers
docker-compose ps

# Você deve ver algo assim:
# NAME                  STATUS
# saira-backend-api     Up
# saira-postgres-db     Up (healthy)
# saira-pgadmin         Up
# vite-react-ts-app     Up
```

## 🗄️ Passo 5: Criar as tabelas do banco de dados

```bash
# Executar migrations do Alembic
docker-compose exec backend alembic upgrade head
```

**Saída esperada:**
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade -> xxx, Initial migration
```

## 🌱 Passo 6: Popular o banco de dados (SEEDING)

```bash
# Executar o script de seeding
docker-compose exec backend python seed_db.py
```

**Saída esperada:**
```
🌱 Iniciando seeding do banco de dados...
👤 Criando usuário Admin...
👥 Criando usuários aleatórios...
✓ Usuários criados com sucesso
📷 Criando câmeras...
✓ Câmeras criadas com sucesso
🔍 Criando detecções...
✓ Detecções criadas com sucesso

✅ Seeding concluído com sucesso!

📝 Credenciais de acesso:
   Email: admin@saira.com
   Senha: admin123
```

## 🌐 Passo 7: Acessar a aplicação

Aguarde cerca de 30 segundos após o seeding e acesse:

- **Frontend**: http://localhost:3000
- **Backend API Docs**: http://localhost:8001/docs
- **pgAdmin**: http://localhost:5050

### 🔐 Credenciais de Login na Aplicação

- **Email**: admin@saira.com
- **Senha**: admin123

### 🔐 Credenciais do pgAdmin (opcional)

- **Email**: admin@saira.com
- **Senha**: admin

## ✅ Passo 8: Testar a aplicação

1. **Acesse** http://localhost:3000
2. **Faça login** com as credenciais acima
3. **Navegue** pelas páginas:
   - Dashboard (veja o mapa com câmeras)
   - Detecções (veja as ocorrências e clique no ícone de mapa)
   - Usuários (crie, edite ou delete usuários)

## 🐛 Troubleshooting

### Problema: "Cannot connect to Docker daemon"
**Solução**: Certifique-se que o Docker Desktop está rodando

### Problema: "Port already in use"
**Solução**:
```bash
# Windows
netstat -ano | findstr :3000
netstat -ano | findstr :8001

# Mate o processo ou mude a porta no docker-compose.yml
```

### Problema: "Frontend não carrega"
**Solução**:
```bash
# Verificar logs do frontend
docker-compose logs web

# Reconstruir o frontend
docker-compose up -d --build web
```

### Problema: "Erro 401 ao fazer login"
**Solução**:
```bash
# Verificar se o backend está rodando
docker-compose logs backend

# Verificar se o seeding foi executado
docker-compose exec backend python seed_db.py

# Testar a API diretamente
# Acesse: http://localhost:8001/docs
```

### Problema: "Banco de dados vazio"
**Solução**:
```bash
# Re-executar seeding
docker-compose exec backend python seed_db.py
```

### Problema: "Mapa não carrega"
**Solução**:
1. Abra o console do navegador (F12)
2. Veja se há erros relacionados a Leaflet
3. Verifique se as câmeras foram criadas:
```bash
docker-compose exec backend python -c "
from app.core.database import AsyncSessionLocal
from app.models.camera import Camera
from sqlalchemy import select
import asyncio

async def check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Camera))
        cameras = result.scalars().all()
        print(f'Total de câmeras: {len(cameras)}')

asyncio.run(check())
"
```

## 🔄 Comandos Úteis

### Ver logs em tempo real
```bash
# Todos os serviços
docker-compose logs -f

# Apenas backend
docker-compose logs -f backend

# Apenas frontend
docker-compose logs -f web
```

### Reiniciar um serviço
```bash
docker-compose restart backend
docker-compose restart web
```

### Acessar shell de um container
```bash
# Backend
docker-compose exec backend bash

# Banco de dados
docker-compose exec db psql -U postgres -d saira_db
```

### Parar tudo
```bash
docker-compose down
```

### Parar tudo e limpar volumes (CUIDADO: apaga o banco)
```bash
docker-compose down -v
```

## 📝 Checklist de Verificação

Antes de reportar problemas, verifique:

- [ ] Docker está rodando
- [ ] Todas as portas necessárias estão livres
- [ ] Containers estão todos "Up": `docker-compose ps`
- [ ] Migrations foram executadas: `docker-compose exec backend alembic upgrade head`
- [ ] Seeding foi executado: `docker-compose exec backend python seed_db.py`
- [ ] Backend está acessível: http://localhost:8001/docs
- [ ] Frontend está acessível: http://localhost:3000

## 🎯 Próximos Passos

Após tudo funcionar:

1. Explore o Dashboard e veja os KPIs em tempo real
2. Veja as câmeras no mapa interativo
3. Navegue para Detecções e clique em "Ver no mapa"
4. Gerencie usuários na página de Usuários
5. Teste a funcionalidade de busca nas detecções

## 📞 Suporte

Se encontrar problemas:

1. Verifique os logs: `docker-compose logs`
2. Consulte o troubleshooting acima
3. Verifique se seguiu todos os passos na ordem
4. Certifique-se que o seeding foi executado com sucesso

---

**Nota**: O seeding cria dados de teste com coordenadas reais de Recife-PE, então o mapa deve funcionar perfeitamente! 🗺️
