# ✅ EXECUTAR AGORA - Passo a Passo Completo

## 🎯 IMPORTANTE: Todas as configurações já foram corrigidas!

### ✅ Correções Aplicadas:
- ✅ Porta do backend ajustada para **8001** em todos os arquivos
- ✅ Frontend configurado para acessar backend em **http://localhost:8001/api/v1**
- ✅ Arquivo .env criado para o frontend
- ✅ Docker-compose.yml corrigido
- ✅ Dockerfile do backend atualizado
- ✅ Todos os imports TypeScript verificados

---

## 🚀 COMANDOS PARA EXECUTAR (na ordem)

### 1. Abrir Terminal/PowerShell
```powershell
# Navegar para o diretório services
cd c:\saira\services
```

### 2. Limpar ambiente anterior (se houver)
```powershell
docker-compose down -v
```

### 3. Construir e iniciar todos os containers
```powershell
docker-compose up -d --build
```
⏳ **Aguarde 2-3 minutos** para os containers iniciarem completamente.

Você pode monitorar com:
```powershell
docker-compose logs -f
```
(Pressione `Ctrl+C` para sair dos logs)

### 4. Verificar se todos os containers estão rodando
```powershell
docker-compose ps
```

Você deve ver:
```
NAME                  STATUS
saira-backend-api     Up
saira-postgres-db     Up (healthy)
saira-pgadmin         Up
vite-react-ts-app     Up
```

### 5. Criar as tabelas do banco de dados
```powershell
docker-compose exec backend alembic upgrade head
```

**Saída esperada:**
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

### 6. Popular o banco de dados (SEEDING)
```powershell
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

### 7. Aguardar 30 segundos

### 8. Acessar a aplicação
Abra no navegador: **http://localhost:3000**

**Credenciais de Login:**
- Email: `admin@saira.com`
- Senha: `admin123`

---

## 🧪 Testar Funcionalidades

### ✅ Dashboard
1. Veja os KPIs (Total de ocorrências, Volume diário)
2. Observe o mapa interativo com as câmeras
3. Clique no botão de expansão do mapa (canto superior direito)

### ✅ Detecções
1. Veja a listagem de detecções
2. Use o campo de busca "Logradouro" para filtrar
3. Clique no ícone 👁️ para ver detalhes
4. Clique no ícone 📍 para ver a localização no mapa

### ✅ Usuários
1. Veja a lista de usuários cadastrados
2. Clique em ➕ para adicionar novo usuário
3. Clique em uma linha para editar
4. Clique no ícone 🗑️ para deletar

---

## 🐛 Resolução de Problemas

### ❌ Problema: "Port already in use"
```powershell
# Windows PowerShell
Get-Process -Id (Get-NetTCPConnection -LocalPort 3000).OwningProcess | Stop-Process -Force
Get-Process -Id (Get-NetTCPConnection -LocalPort 8001).OwningProcess | Stop-Process -Force
```

### ❌ Problema: "Cannot connect to Docker"
**Solução:** Abra o Docker Desktop e aguarde iniciar completamente

### ❌ Problema: Frontend não carrega
```powershell
# Ver logs
docker-compose logs web

# Reconstruir
docker-compose up -d --build web
```

### ❌ Problema: Erro 401 ao fazer login
```powershell
# Verificar se seeding foi executado
docker-compose exec backend python seed_db.py

# Testar API diretamente
# Abra: http://localhost:8001/docs
```

### ❌ Problema: Mapa não aparece
1. Pressione F12 no navegador
2. Vá para a aba "Console"
3. Procure por erros relacionados a "leaflet" ou "map"
4. Verifique se as câmeras foram criadas:
```powershell
docker-compose exec db psql -U postgres -d saira_db -c "SELECT COUNT(*) FROM cameras;"
```

---

## 📊 URLs de Acesso

| Serviço | URL | Descrição |
|---------|-----|-----------|
| **Frontend** | http://localhost:3000 | Aplicação principal |
| **Backend API** | http://localhost:8001/docs | Documentação interativa da API |
| **pgAdmin** | http://localhost:5050 | Interface de gerenciamento do banco |
| **PostgreSQL** | localhost:5432 | Banco de dados (via cliente SQL) |

---

## 🔄 Comandos Úteis

### Ver logs em tempo real
```powershell
# Todos os serviços
docker-compose logs -f

# Apenas backend
docker-compose logs -f backend

# Apenas frontend
docker-compose logs -f web
```

### Reiniciar um serviço
```powershell
docker-compose restart backend
docker-compose restart web
```

### Acessar shell de um container
```powershell
# Backend (Python)
docker-compose exec backend bash

# Banco de dados (psql)
docker-compose exec db psql -U postgres -d saira_db
```

### Verificar tabelas do banco
```powershell
docker-compose exec db psql -U postgres -d saira_db -c "\dt"
```

### Contar registros
```powershell
docker-compose exec db psql -U postgres -d saira_db -c "SELECT 'users' as tabela, COUNT(*) FROM users UNION ALL SELECT 'cameras', COUNT(*) FROM cameras UNION ALL SELECT 'detections', COUNT(*) FROM detections;"
```

---

## 🎯 Checklist Final

Antes de reportar problemas, verifique:

- [ ] Docker Desktop está rodando
- [ ] Executei `docker-compose down -v` antes de começar
- [ ] Executei `docker-compose up -d --build`
- [ ] Aguardei 2-3 minutos após o build
- [ ] Todos os containers estão "Up": `docker-compose ps`
- [ ] Executei `alembic upgrade head` com sucesso
- [ ] Executei `python seed_db.py` e vi a mensagem de sucesso
- [ ] Vi as credenciais: admin@saira.com / admin123
- [ ] Aguardei 30 segundos após o seeding
- [ ] Testei http://localhost:8001/docs (API está respondendo)
- [ ] Testei http://localhost:3000 (Frontend carrega)

---

## 🎉 Sucesso!

Se tudo funcionou:
- ✅ Você verá o mapa com pins de câmeras
- ✅ Poderá fazer login e navegar
- ✅ Verá dados reais de Recife nas detecções
- ✅ Poderá gerenciar usuários

**Divirta-se explorando o SAIRA! 🗺️**

---

## 📞 Próximos Passos

1. Explore todas as funcionalidades
2. Teste criar/editar/deletar usuários
3. Veja as detecções no mapa
4. Acesse http://localhost:8001/docs para ver a API
5. Use o pgAdmin para explorar o banco de dados

**Nota:** Todos os dados são fictícios criados pelo Faker, mas as coordenadas são reais de Recife-PE! 🌎
