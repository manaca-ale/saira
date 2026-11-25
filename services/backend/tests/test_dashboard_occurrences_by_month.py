"""Regressão: GET /dashboard/occurrences-by-month dava 500 em produção e teste (achado em 24/11/2026).

Sintoma: `asyncpg.exceptions.GroupingError: column "detections.timestamp" must appear in the GROUP BY
clause or be used in an aggregate function`, e o gráfico mensal do painel não carregava.

Causa: o formato 'YYYY-MM' de `to_char` ia como parâmetro (`$1`, `$2`, `$3`) separado no SELECT, no
GROUP BY e no ORDER BY. Para o Postgres, `to_char(timestamp, $1)` e `to_char(timestamp, $2)` são
expressões diferentes, então o SELECT não está agrupado. O teste compila a consulta que o endpoint
executa no dialeto asyncpg (o de produção) e exige o mesmo texto, sem parâmetro, nas três cláusulas.
"""
import re
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.api.v1.endpoints.dashboard import get_occurrences_by_month
from tests.conftest import FakeUser


async def _sql_executado() -> str:
    resultado = MagicMock()
    resultado.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=resultado)

    await get_occurrences_by_month(db=db, current_user=FakeUser())

    stmt = db.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.asyncpg.dialect()))


def _expressao_mes(trecho: str) -> str:
    achado = re.search(r"to_char\([^)]*\)", trecho)
    assert achado, f"to_char não encontrado em: {trecho}"
    return achado.group(0)


async def test_group_by_usa_a_mesma_expressao_do_select_sem_parametro():
    sql = await _sql_executado()
    select_parte, resto = re.split(r"\sFROM\s", sql, maxsplit=1)
    group_parte = re.split(r"\sORDER BY\s", re.split(r"\sGROUP BY\s", resto, maxsplit=1)[1], maxsplit=1)[0]
    order_parte = re.split(r"\sORDER BY\s", resto, maxsplit=1)[1]

    no_select = _expressao_mes(select_parte)
    assert "$" not in no_select and "%(" not in no_select, f"formato do mês virou parâmetro: {no_select}"
    assert _expressao_mes(group_parte) == no_select, sql
    assert _expressao_mes(order_parte) == no_select, sql


async def test_devolve_lista_de_meses():
    linha = MagicMock(month="2026-08", count=3)
    resultado = MagicMock()
    resultado.all.return_value = [linha]
    db = MagicMock()
    db.execute = AsyncMock(return_value=resultado)

    saida = await get_occurrences_by_month(db=db, current_user=FakeUser())

    assert [(m.month, m.count) for m in saida] == [("2026-08", 3)]
