# 🚀 INÍCIO RÁPIDO - SAIRA

## ⚡ Comandos Rápidos (Copy & Paste)

### 1️⃣ Limpar ambiente anterior
```bash
cd c:\saira\services
docker-compose down -v
```

### 2️⃣ Subir todos os serviços
```bash
docker-compose up -d --build
```

**⏳ Aguarde 2-3 minutos** para os containers iniciarem.

### 3️⃣ Criar tabelas do banco
```bash
docker-compose exec backend alembic upgrade head
```

### 4️⃣ Popular banco de dados
```bash
docker-compose exec backend python seed_db.py
```

### 5️⃣ Acessar aplicação
Abra no navegador: **http://localhost:3000**

**Login:**
- Email: `admin@saira.com`
- Senha: `admin123`

---

## 📊 URLs Importantes

| Serviço | URL | Credenciais |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | admin@saira.com / admin123 |
| Backend API | http://localhost:8001/docs | - |
| pgAdmin | http://localhost:5050 | admin@saira.com / admin |

---

## ❓ Problemas?

### Frontend não abre
```bash
docker-compose logs web
docker-compose restart web
```

### Login não funciona
```bash
# Re-executar seeding
docker-compose exec backend python seed_db.py
```

### Mapa não carrega
1. Abra F12 no navegador
2. Veja erros no Console
3. Verifique se há câmeras:
```bash
docker-compose exec db psql -U postgres -d saira_db -c "SELECT COUNT(*) FROM cameras;"
```

### Recomeçar do zero
```bash
docker-compose down -v
docker-compose up -d --build
docker-compose exec backend alembic upgrade head
docker-compose exec backend python seed_db.py
```

---

## ✅ Checklist

- [ ] Docker Desktop está rodando
- [ ] Portas 3000, 8001, 5432 estão livres
- [ ] Executei `docker-compose up -d --build`
- [ ] Executei `alembic upgrade head`
- [ ] Executei `python seed_db.py`
- [ ] Vi a mensagem de sucesso do seeding
- [ ] Aguardei 30 segundos após o seeding
- [ ] Acessei http://localhost:3000

---

**💡 Dica:** Para ver logs em tempo real: `docker-compose logs -f`
