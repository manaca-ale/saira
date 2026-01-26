# 🗺️ SAIRA - Sistema de Monitoramento de Descarte Irregular

## ✅ Status: PRONTO PARA EXECUÇÃO

> **Implementação 100% Completa** - Frontend React + Backend FastAPI + PostgreSQL/PostGIS

---

## 🚀 INÍCIO RÁPIDO - LEIA PRIMEIRO

### 📖 Guia Principal de Execução
**👉 [EXECUTAR_AGORA.md](./EXECUTAR_AGORA.md) 👈**

Este é o guia completo passo a passo. Siga-o na ordem!

### ⚡ Comandos Resumidos
```bash
cd c:\saira\services
docker-compose down -v
docker-compose up -d --build
docker-compose exec backend alembic upgrade head
docker-compose exec backend python seed_db.py
```

**Acesse:** http://localhost:3000  
**Login:** admin@saira.com / admin123

---

## 📚 Documentação Disponível

| Documento | Quando Usar |
|-----------|-------------|
| **[EXECUTAR_AGORA.md](./EXECUTAR_AGORA.md)** | 🎯 Primeira execução - Guia completo |
| [START.md](./START.md) | ⚡ Comandos rápidos |
| [RESUMO_CORRECOES.md](./RESUMO_CORRECOES.md) | 📋 O que foi corrigido |
| [README_IMPLEMENTACAO.md](./README_IMPLEMENTACAO.md) | 📖 Documentação técnica |

---

## 🏗️ Tecnologias

- **Frontend:** React 19 + Vite + TypeScript + Tailwind CSS + Leaflet
- **Backend:** FastAPI + PostgreSQL 15 + PostGIS + JWT
- **DevOps:** Docker + Docker Compose + Nginx

---

## 🎯 Funcionalidades

✅ Dashboard com KPIs em tempo real  
✅ Mapa interativo com câmeras (Leaflet)  
✅ Gerenciamento de detecções  
✅ CRUD completo de usuários  
✅ Autenticação JWT  
✅ Filtros e buscas  

---

## 🌐 URLs

- Frontend: http://localhost:3000
- Backend API: http://localhost:8001/docs
- pgAdmin: http://localhost:5050

---

## 🔐 Credenciais

**Login na Aplicação:**
- Email: admin@saira.com
- Senha: admin123

---

## 🐛 Problemas?

Consulte [EXECUTAR_AGORA.md](./EXECUTAR_AGORA.md) seção "Resolução de Problemas"

---

## ✅ Tudo Pronto!

Todos os arquivos estão configurados e testados.  
Siga o [EXECUTAR_AGORA.md](./EXECUTAR_AGORA.md) e o sistema funcionará! 🚀
