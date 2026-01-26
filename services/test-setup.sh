#!/bin/bash

echo "================================="
echo "🧪 TESTE DE CONFIGURAÇÃO - SAIRA"
echo "================================="
echo ""

# Verificar se está no diretório correto
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Erro: Execute este script do diretório services/"
    exit 1
fi

echo "✅ Diretório correto"
echo ""

# Verificar arquivos essenciais do backend
echo "📂 Verificando arquivos do backend..."
files=(
    "backend/Dockerfile"
    "backend/requirements.txt"
    "backend/seed_db.py"
    "backend/app/main.py"
    "backend/app/core/config.py"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file"
    else
        echo "  ❌ $file - FALTANDO!"
    fi
done

echo ""

# Verificar arquivos essenciais do frontend
echo "📂 Verificando arquivos do frontend..."
files=(
    "frontend/Dockerfile"
    "frontend/package.json"
    "frontend/src/services/api.ts"
    "frontend/src/contexts/AuthContext.tsx"
    "frontend/src/pages/Login.tsx"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file"
    else
        echo "  ❌ $file - FALTANDO!"
    fi
done

echo ""

# Verificar se Docker está rodando
echo "🐳 Verificando Docker..."
if docker info > /dev/null 2>&1; then
    echo "  ✅ Docker está rodando"
else
    echo "  ❌ Docker não está rodando!"
    echo "  💡 Inicie o Docker Desktop e tente novamente"
    exit 1
fi

echo ""

# Verificar portas
echo "🔌 Verificando portas..."
ports=(3000 8001 5432 5050)
for port in "${ports[@]}"; do
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo "  ⚠️  Porta $port está em uso"
    else
        echo "  ✅ Porta $port está livre"
    fi
done

echo ""
echo "================================="
echo "✅ Verificação concluída!"
echo "================================="
echo ""
echo "Próximos passos:"
echo "1. docker-compose down -v"
echo "2. docker-compose up -d --build"
echo "3. docker-compose exec backend alembic upgrade head"
echo "4. docker-compose exec backend python seed_db.py"
echo "5. Acesse: http://localhost:3000"
