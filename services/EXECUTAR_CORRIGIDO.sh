#!/bin/bash

echo "============================================"
echo "🚀 EXECUTAR SAIRA - VERSÃO CORRIGIDA"
echo "============================================"
echo ""

echo "📝 Correção aplicada: AuthContext.tsx"
echo "   - ReactNode agora usa import type"
echo ""

echo "Iniciando processo..."
echo ""

# Verificar Docker
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker não está rodando!"
    echo "   Inicie o Docker Desktop primeiro"
    exit 1
fi

echo "✅ Docker está rodando"
echo ""

# Limpar ambiente
echo "🧹 Limpando ambiente anterior..."
docker-compose down -v 2>&1 | grep -v "Warning"

echo ""
echo "🏗️  Construindo containers (isso pode levar 3-5 minutos)..."
echo "   Por favor, aguarde..."
echo ""

docker-compose up -d --build

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Erro ao construir containers"
    echo "   Verifique os logs acima"
    exit 1
fi

echo ""
echo "⏳ Aguardando containers iniciarem (30 segundos)..."
sleep 30

echo ""
echo "📊 Status dos containers:"
docker-compose ps

echo ""
echo "🗄️  Criando tabelas do banco de dados..."
docker-compose exec backend alembic upgrade head

if [ $? -ne 0 ]; then
    echo "❌ Erro ao criar tabelas"
    exit 1
fi

echo ""
echo "🌱 Populando banco de dados..."
docker-compose exec backend python seed_db.py

if [ $? -ne 0 ]; then
    echo "❌ Erro ao popular banco"
    exit 1
fi

echo ""
echo "============================================"
echo "✅ SISTEMA PRONTO!"
echo "============================================"
echo ""
echo "🌐 URLs de Acesso:"
echo "   Frontend:    http://localhost:3000"
echo "   Backend API: http://localhost:8001/docs"
echo "   pgAdmin:     http://localhost:5050"
echo ""
echo "🔐 Credenciais:"
echo "   Email: admin@saira.com"
echo "   Senha: admin123"
echo ""
echo "📝 Para ver logs:"
echo "   docker-compose logs -f"
echo ""
echo "🎉 Tudo pronto! Abra http://localhost:3000 no navegador"
echo ""
