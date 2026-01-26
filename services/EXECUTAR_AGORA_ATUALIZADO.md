# ✅ EXECUTAR AGORA - Versão Corrigida

## 🎯 CORREÇÃO APLICADA - Pronto para executar!

**Erro corrigido:** Import de tipo ReactNode no AuthContext.tsx

---

## 🚀 COMANDOS PARA EXECUTAR (Copy & Paste)

### No PowerShell ou CMD (Windows):

```powershell
# 1. Ir para o diretório
cd c:\saira\services

# 2. Limpar ambiente anterior
docker-compose down -v

# 3. Construir e iniciar (AGUARDE 3-5 minutos)
docker-compose up -d --build

# 4. Aguardar containers iniciarem (execute após o build)
timeout /t 30

# 5. Verificar se está rodando
docker-compose ps

# 6. Criar tabelas do banco
docker-compose exec backend alembic upgrade head

# 7. Popular banco de dados
docker-compose exec backend python seed_db.py

# 8. Aguardar 30 segundos
timeout /t 30

# 9. Pronto! Acesse: http://localhost:3000
```

---

## 🔐 Credenciais de Acesso

**Login:**
- Email: `admin@saira.com`
- Senha: `admin123`

---

## 📊 Verificar se está funcionando

### ✅ Containers rodando:
```powershell
docker-compose ps
```

Você deve ver todos com status "Up":
- saira-backend-api → Up
- saira-postgres-db → Up (healthy)
- vite-react-ts-app → Up
- saira-pgadmin → Up

### ✅ Backend funcionando:
Abra: http://localhost:8001/docs

Você deve ver a documentação Swagger da API

### ✅ Frontend funcionando:
Abra: http://localhost:3000

Você deve ver a tela de login

---

## 🐛 Se algo der errado

### ❌ Erro de compilação ainda aparece
```powershell
# Verificar se a correção foi aplicada
type frontend\src\contexts\AuthContext.tsx | findstr "import type"
```

Deve mostrar: `import type { ReactNode } from 'react';`

### ❌ Container não sobe
```powershell
# Ver logs
docker-compose logs web
docker-compose logs backend
```

### ❌ Frontend não carrega
```powershell
# Reconstruir apenas o frontend
docker-compose up -d --build web

# Ver logs em tempo real
docker-compose logs -f web
```

### ❌ Login não funciona
```powershell
# Re-executar seeding
docker-compose exec backend python seed_db.py

# Verificar se o admin existe
docker-compose exec db psql -U postgres -d saira_db -c "SELECT email FROM users WHERE email='admin@saira.com';"
```

### ❌ Mapa não aparece
1. Abra o Console do navegador (F12)
2. Veja se há erros
3. Verifique se as câmeras existem:
```powershell
docker-compose exec db psql -U postgres -d saira_db -c "SELECT COUNT(*) FROM cameras;"
```

---

## 📝 Comandos Úteis

### Ver logs em tempo real:
```powershell
docker-compose logs -f
```

### Ver logs apenas do backend:
```powershell
docker-compose logs -f backend
```

### Ver logs apenas do frontend:
```powershell
docker-compose logs -f web
```

### Reiniciar um serviço:
```powershell
docker-compose restart backend
docker-compose restart web
```

### Acessar shell do backend:
```powershell
docker-compose exec backend bash
```

### Verificar tabelas do banco:
```powershell
docker-compose exec db psql -U postgres -d saira_db -c "\dt"
```

### Contar registros:
```powershell
docker-compose exec db psql -U postgres -d saira_db -c "SELECT 'users' as tabela, COUNT(*) FROM users UNION ALL SELECT 'cameras', COUNT(*) FROM cameras UNION ALL SELECT 'detections', COUNT(*) FROM detections;"
```

---

## 🎯 Checklist Final

Antes de reportar problemas:

- [ ] Docker Desktop está rodando
- [ ] Executei `docker-compose down -v`
- [ ] Executei `docker-compose up -d --build`
- [ ] Aguardei 3-5 minutos para o build completar
- [ ] Todos os containers estão "Up": `docker-compose ps`
- [ ] Executei `alembic upgrade head`
- [ ] Executei `python seed_db.py`
- [ ] Vi a mensagem de sucesso do seeding
- [ ] Aguardei 30 segundos
- [ ] Testei http://localhost:8001/docs (carrega)
- [ ] Testei http://localhost:3000 (carrega)

---

## 🌐 URLs Importantes

| Serviço | URL | Credenciais |
|---------|-----|-------------|
| **Frontend** | http://localhost:3000 | admin@saira.com / admin123 |
| **Backend API** | http://localhost:8001/docs | - |
| **pgAdmin** | http://localhost:5050 | admin@saira.com / admin |

---

## 🎉 O que testar

### 1. Dashboard
- Veja os KPIs atualizados
- Explore o mapa com as câmeras
- Clique no botão de expandir o mapa

### 2. Detecções
- Veja a listagem de detecções
- Use o filtro de busca por logradouro
- Clique no ícone 👁️ para ver detalhes
- Clique no ícone 📍 para ver no mapa

### 3. Usuários
- Veja a lista de usuários
- Clique em ➕ para adicionar
- Clique em uma linha para editar
- Clique em 🗑️ para deletar

---

## 📞 Ainda com problemas?

1. Verifique os logs: `docker-compose logs`
2. Leia [CORRECAO_APLICADA.md](./CORRECAO_APLICADA.md)
3. Leia [RESUMO_CORRECOES.md](./RESUMO_CORRECOES.md)
4. Execute `docker-compose down -v` e tente novamente

---

## ✅ Sucesso!

Se tudo funcionou:
- ✅ Você vê a tela de login
- ✅ Consegue fazer login com admin@saira.com
- ✅ Vê o dashboard com o mapa
- ✅ As detecções aparecem
- ✅ Pode gerenciar usuários

**Parabéns! O SAIRA está funcionando! 🎉🗺️**
