"""Política de senha (docs/specs/acesso-usuarios.md).

Comprimento e lista de bloqueio, sem regra de composição (NIST SP 800-63B):
regra de "número e símbolo" só gera Senha@123.
"""
from __future__ import annotations

from typing import Optional

MIN_LENGTH = 8
MAX_LENGTH = 128

# Senhas óbvias que passam no mínimo de 8 caracteres.
_BLOCKLIST = frozenset({
    "12345678", "123456789", "1234567890", "87654321", "11111111", "00000000",
    "password", "password1", "senha123", "senha1234", "mudar123", "trocar123",
    "saira123", "saira2026", "recife123", "prefeitura", "qwertyui", "qwerty123",
    "abcd1234", "abc12345", "admin123", "administrador", "iloveyou", "asdfghjk",
})


def password_problem(password: str, email: Optional[str] = None) -> Optional[str]:
    """Motivo, em português, de a senha não servir; None se ela serve."""
    if len(password) < MIN_LENGTH:
        return f"A senha precisa ter pelo menos {MIN_LENGTH} caracteres."
    if len(password) > MAX_LENGTH:
        return f"A senha pode ter no máximo {MAX_LENGTH} caracteres."
    lowered = password.strip().lower()
    if len(set(lowered)) == 1:
        return "A senha não pode ser um caractere repetido."
    if lowered in _BLOCKLIST:
        return "Essa senha é muito comum. Escolha outra."
    if email:
        email_l = email.strip().lower()
        if lowered in {email_l, email_l.split("@", 1)[0]}:
            return "A senha não pode ser o seu e-mail."
    return None
