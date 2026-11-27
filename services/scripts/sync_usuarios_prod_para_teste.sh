#!/usr/bin/env bash
# Copia os usuários da produção para o banco de teste, para que cada pessoa
# entre no teste com o mesmo e-mail e a mesma senha da produção
# (pedido do Alexandre, 26/11/2026).
#
# - Só produção -> teste. Nunca escreve na produção (lá só roda SELECT).
# - Casa por e-mail: atualiza quem já existe no teste e cria quem falta.
# - Nunca apaga usuário do teste (contas só de teste continuam).
# - Pula as contas de serviço (por padrão admin@saira.com, que o esp32-server
#   de cada ambiente usa com a senha do próprio .env).
# - A senha só é criada e trocada na produção; o teste acompanha nesta cópia.
#   Tokens de convite e de recuperação não são copiados: cada ambiente tem os seus.
# - Copia token_version também: trocar a senha na produção derruba as sessões
#   do teste na cópia seguinte, como na produção.
#
# Cron sugerido (de hora em hora, no host):
#   17 * * * * /home/ubuntu/saira/services/scripts/sync_usuarios_prod_para_teste.sh >> /home/ubuntu/logs/sync-usuarios.log 2>&1
set -euo pipefail

PROD_DB="${PROD_DB_CONTAINER:-saira-db-prod}"
TEST_DB="${TEST_DB_CONTAINER:-saira-db-test}"
DB_NAME="${SYNC_DB_NAME:-saira_db}"
DB_USER="${SYNC_DB_USER:-postgres}"
# Lista separada por vírgula, comparada sem diferenciar maiúsculas.
SKIP="${SYNC_SKIP_EMAILS:-admin@saira.com}"

COLS="email, name, phone, secretaria, cargo, rpa, password_hash, must_change_password, token_version, password_changed_at, auth_provider, is_active, created_at, updated_at"

skip_sql=$(printf '%s' "$SKIP" | tr 'A-Z' 'a-z' | awk -F',' '{for(i=1;i<=NF;i++){gsub(/^ +| +$/,"",$i); gsub(/'\''/,"",$i); if($i!="") printf "%s'\''%s'\''", (n++?",":""), $i}}')
[ -n "$skip_sql" ] || skip_sql="''"

echo "$(date -Is) início: $PROD_DB -> $TEST_DB (pula: $SKIP)"

# Lê a produção inteira antes de abrir a transação no teste: se a leitura falhar,
# o teste nem é tocado.
dados=$(docker exec "$PROD_DB" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" -At \
  -c "COPY (SELECT $COLS FROM users WHERE lower(email) NOT IN ($skip_sql)) TO STDOUT WITH (FORMAT csv)")
[ -n "$dados" ] || { echo "$(date -Is) produção sem usuários para copiar; nada feito"; exit 1; }

{
cat <<SQL
BEGIN;
CREATE TEMP TABLE prod_users ON COMMIT DROP AS SELECT $COLS FROM users WITH NO DATA;
COPY prod_users ($COLS) FROM STDIN WITH (FORMAT csv);
SQL
printf '%s\n\\.\n' "$dados"
cat <<SQL
UPDATE users t SET
  name = p.name, phone = p.phone, secretaria = p.secretaria, cargo = p.cargo, rpa = p.rpa,
  password_hash = p.password_hash, must_change_password = p.must_change_password,
  token_version = p.token_version, password_changed_at = p.password_changed_at,
  auth_provider = p.auth_provider, is_active = p.is_active, updated_at = p.updated_at
FROM prod_users p
WHERE lower(t.email) = lower(p.email)
  AND lower(t.email) NOT IN ($skip_sql)
  AND (t.password_hash IS DISTINCT FROM p.password_hash OR t.name IS DISTINCT FROM p.name
       OR t.cargo IS DISTINCT FROM p.cargo OR t.is_active IS DISTINCT FROM p.is_active
       OR t.must_change_password IS DISTINCT FROM p.must_change_password
       OR t.token_version IS DISTINCT FROM p.token_version OR t.phone IS DISTINCT FROM p.phone
       OR t.secretaria IS DISTINCT FROM p.secretaria OR t.rpa IS DISTINCT FROM p.rpa
       OR t.auth_provider IS DISTINCT FROM p.auth_provider);
INSERT INTO users ($COLS)
SELECT $COLS FROM prod_users p
WHERE NOT EXISTS (SELECT 1 FROM users t WHERE lower(t.email) = lower(p.email));
COMMIT;
SQL
} | docker exec -i "$TEST_DB" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" -q

echo "$(date -Is) fim: $(docker exec "$TEST_DB" psql -U "$DB_USER" -d "$DB_NAME" -At -c 'select count(*) from users') usuários no teste"
