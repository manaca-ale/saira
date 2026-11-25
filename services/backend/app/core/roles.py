"""Papéis de acesso (RBAC) derivados do campo `cargo` do usuário.

O banco não tem coluna de papel: o `cargo` é texto livre. Administrador é quem
tem `cargo` igual a "Administrador" ou "admin" (sem diferenciar maiúsculas e
espaços nas pontas). Qualquer outro valor, inclusive vazio, é operador.
Todo usuário ativo é pelo menos operador.
"""
from enum import Enum
from typing import Optional


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operador"


ADMIN_CARGOS = frozenset({"administrador", "admin"})


def role_from_cargo(cargo: Optional[str]) -> Role:
    if (cargo or "").strip().lower() in ADMIN_CARGOS:
        return Role.ADMIN
    return Role.OPERATOR


def is_admin(user) -> bool:
    return role_from_cargo(getattr(user, "cargo", None)) is Role.ADMIN
