"""Garantias do services/scripts/sync_usuarios_prod_para_teste.sh (26/11/2026).

O script copia os usuários da produção para o teste (mesmo e-mail, mesma senha).
Estes testes leem o script e travam o que não pode mudar sem querer:
a produção só é lida, a conta de serviço do esp32-server fica de fora,
nada é apagado no teste e a escrita no teste acontece numa transação.
"""
from pathlib import Path
import re

SCRIPT = Path(__file__).resolve().parents[2] / "services" / "scripts" / "sync_usuarios_prod_para_teste.sh"


def _texto() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _comandos_na_producao(texto: str) -> list[str]:
    """Trechos passados ao psql do contêiner da produção."""
    trechos = []
    for m in re.finditer(r'docker exec "\$PROD_DB" psql(.*?)\)\s*$', texto, flags=re.S | re.M):
        trechos.append(m.group(1))
    return trechos


def test_producao_so_e_lida():
    texto = _texto()
    trechos = _comandos_na_producao(texto)
    assert len(trechos) == 1, "esperava uma única chamada ao banco da produção"
    sql = trechos[0].upper()
    assert "COPY (SELECT" in sql and "TO STDOUT" in sql
    for proibido in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALTER", "DROP", "FROM STDIN"):
        assert proibido not in sql, f"{proibido} não pode ir para a produção"
    # Nenhum outro "docker exec -i" (escrita por stdin) aponta para a produção.
    assert 'docker exec -i "$PROD_DB"' not in texto


def test_conta_de_servico_fica_de_fora_por_padrao():
    texto = _texto()
    assert re.search(r'SKIP="\$\{SYNC_SKIP_EMAILS:-admin@saira\.com\}"', texto)
    # o filtro vale na leitura e no UPDATE do teste
    assert texto.count("NOT IN ($skip_sql)") >= 2


def test_nunca_apaga_no_teste_e_usa_transacao():
    texto = _texto().upper()
    assert "DELETE" not in texto and "TRUNCATE" not in texto
    assert "BEGIN;" in texto and "COMMIT;" in texto
    assert "ON_ERROR_STOP=1" in texto
    assert "SET -EUO PIPEFAIL" in texto


def test_nao_copia_tokens_nem_id():
    texto = _texto()
    cols = re.search(r'^COLS="([^"]+)"', texto, flags=re.M).group(1)
    nomes = [c.strip() for c in cols.split(",")]
    assert "id" not in nomes
    assert "password_hash" in nomes and "email" in nomes
    assert "user_action_tokens" not in texto
