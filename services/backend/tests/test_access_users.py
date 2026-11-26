"""Convite, "esqueci minha senha" e troca obrigatória (frente saira-acesso-usuarios, 25/11/2026).

Antes: o administrador escolhia a senha de cada usuário e precisava entregá-la
por fora (e-mail); "Esqueceu a senha?" só abria um mailto. Agora: link de uso
único por e-mail (só o hash no banco), senha provisória obrigada a trocar e
sessões derrubadas na troca. Desenho em docs/specs/acesso-usuarios.md.

Banco: SQLite em memória (aiosqlite) só com as tabelas users e
user_action_tokens, para exercitar o SQL de verdade. E-mail sempre mockado.
"""
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registra todos os mapeamentos)
from app.core import rate_limit
from app.core.database import Base
from app.core.security import create_user_access_token, get_password_hash, verify_password
from app.models.user import User
from app.models.user_action_token import UserActionToken
from app.services import access_email, access_service

API = "/api/v1"
ADMIN_PASSWORD = "admin-senha-longa-1"


@pytest_asyncio.fixture
async def sessionmaker_():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[User.__table__, UserActionToken.__table__]
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_rate_limit():
    rate_limit.clear_memory()
    yield
    rate_limit.clear_memory()


@pytest.fixture
def sent(monkeypatch):
    """Captura os e-mails em vez de chamar o Resend."""
    outbox = []

    def fake_send_email(**kwargs):
        outbox.append(kwargs)
        return True

    monkeypatch.setattr(access_email.email_service, "send_email", fake_send_email)
    return outbox


async def _add_user(sm, email, password=None, cargo="Operador", must_change=False, is_active=True, name=None):
    async with sm() as db:
        user = User(
            name=name or email.split("@")[0].title(),
            email=email,
            cargo=cargo,
            password_hash=get_password_hash(password) if password else None,
            must_change_password=must_change,
            token_version=0,
            is_active=is_active,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _get_user(sm, email):
    async with sm() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one()


@pytest_asyncio.fixture
async def api(sessionmaker_):
    from app.main import app
    from app.api.deps import get_db

    async def override_get_db():
        async with sessionmaker_() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin(sessionmaker_):
    user = await _add_user(sessionmaker_, "admin@saira.com", ADMIN_PASSWORD, cargo="Administrador", name="Alexandre Coleto")
    return user, {"Authorization": f"Bearer {create_user_access_token(user)}"}


def _token_from(mail) -> str:
    text = mail["text_body"]
    assert "/definir-senha#token=" in text
    return text.split("#token=", 1)[1].split()[0]


async def _login(api, email, password):
    return await api.post(f"{API}/auth/login", data={"username": email, "password": password})


# ── Serviço de tokens ───────────────────────────────────────────────────


async def test_token_is_stored_only_as_hash(sessionmaker_):
    user = await _add_user(sessionmaker_, "a@saira.com")
    async with sessionmaker_() as db:
        raw = await access_service.issue_token(db, user, access_service.PURPOSE_INVITE)
        await db.commit()
        rows = (await db.execute(select(UserActionToken))).scalars().all()
    assert len(raw) >= 43  # 32 bytes aleatórios
    assert len(rows) == 1
    assert rows[0].token_hash == access_service.hash_token(raw)
    assert raw not in rows[0].token_hash


async def test_valid_expired_used_and_tampered_tokens(sessionmaker_):
    user = await _add_user(sessionmaker_, "b@saira.com")
    async with sessionmaker_() as db:
        raw = await access_service.issue_token(db, user, access_service.PURPOSE_RESET)
        await db.commit()

        check = await access_service.check_token(db, raw)
        assert check.user.email == "b@saira.com" and check.token.purpose == "reset"

        tampered = raw[:-1] + ("A" if raw[-1] != "A" else "B")
        with pytest.raises(access_service.TokenError) as exc:
            await access_service.check_token(db, tampered)
        assert exc.value.code == access_service.TOKEN_INVALID

        await access_service.consume_token_and_set_password(db, raw, "senha-nova-forte")
        await db.commit()
        with pytest.raises(access_service.TokenError) as exc:
            await access_service.consume_token_and_set_password(db, raw, "outra-senha-forte")
        assert exc.value.code == access_service.TOKEN_USED

        raw2 = await access_service.issue_token(db, user, access_service.PURPOSE_RESET)
        await db.execute(
            update(UserActionToken)
            .where(UserActionToken.token_hash == access_service.hash_token(raw2))
            .values(expires_at=access_service.utcnow() - timedelta(seconds=1))
        )
        await db.commit()
        with pytest.raises(access_service.TokenError) as exc:
            await access_service.check_token(db, raw2)
        assert exc.value.code == access_service.TOKEN_EXPIRED


async def test_new_token_invalidates_previous_pending_one(sessionmaker_):
    user = await _add_user(sessionmaker_, "c@saira.com")
    async with sessionmaker_() as db:
        first = await access_service.issue_token(db, user, access_service.PURPOSE_INVITE)
        second = await access_service.issue_token(db, user, access_service.PURPOSE_INVITE)
        await db.commit()
        with pytest.raises(access_service.TokenError) as exc:
            await access_service.check_token(db, first)
        assert exc.value.code == access_service.TOKEN_INVALID
        assert (await access_service.check_token(db, second)).user.id == user.id


async def test_token_of_inactive_user_is_invalid(sessionmaker_):
    user = await _add_user(sessionmaker_, "d@saira.com", is_active=False)
    async with sessionmaker_() as db:
        raw = await access_service.issue_token(db, user, access_service.PURPOSE_INVITE)
        await db.commit()
        with pytest.raises(access_service.TokenError):
            await access_service.check_token(db, raw)


def test_link_carries_token_in_fragment_not_query(monkeypatch):
    monkeypatch.setattr(access_service.settings, "APP_PUBLIC_URL", "https://saira.manaca.tech/")
    link = access_service.password_link("abc")
    assert link == "https://saira.manaca.tech/definir-senha#token=abc"


def test_link_falls_back_to_dashboard_url(monkeypatch):
    monkeypatch.setattr(access_service.settings, "APP_PUBLIC_URL", "")
    monkeypatch.setattr(access_service.settings, "REPORT_DASHBOARD_URL", "https://test-saira.manaca.tech")
    assert access_service.password_link("x").startswith("https://test-saira.manaca.tech/definir-senha#")


# ── Convite ─────────────────────────────────────────────────────────────


async def test_admin_creates_user_without_password_and_invite_works_end_to_end(api, admin, sent, sessionmaker_):
    _, headers = admin
    response = await api.post(
        f"{API}/users/",
        headers=headers,
        json={"name": "Rayssa Teste", "email": "rayssa@example.com", "cargo": "Administrador"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invite_pending"] is True and body["invite_email_sent"] is True
    assert "password" not in body and "password_hash" not in body

    assert len(sent) == 1
    mail = sent[0]
    assert mail["to_addrs"] == ["rayssa@example.com"]
    assert mail["subject"] == "Seu acesso ao SAÍRA"
    assert "Alexandre Coleto" in mail["text_body"] and "48 horas" in mail["text_body"]
    assert "<a href=" in mail["html_body"]
    token = _token_from(mail)

    # Sem senha ainda: nenhuma senha serve no login.
    assert (await _login(api, "rayssa@example.com", "qualquer-coisa")).status_code == 401

    info = await api.post(f"{API}/auth/password/token", json={"token": token})
    assert info.status_code == 200, info.text
    assert info.json()["purpose"] == "invite" and info.json()["name"] == "Rayssa Teste"

    done = await api.post(f"{API}/auth/password/set", json={"token": token, "password": "minha-senha-nova"})
    assert done.status_code == 200, done.text
    assert done.json()["email"] == "rayssa@example.com"

    login = await _login(api, "rayssa@example.com", "minha-senha-nova")
    assert login.status_code == 200, login.text
    assert login.json()["must_change_password"] is False

    # Link reutilizado
    again = await api.post(f"{API}/auth/password/set", json={"token": token, "password": "outra-senha-nova"})
    assert again.status_code == 400 and again.json()["detail"] == "token_used"
    assert (await _login(api, "rayssa@example.com", "minha-senha-nova")).status_code == 200

    user = await _get_user(sessionmaker_, "rayssa@example.com")
    assert user.invite_pending is False and user.token_version == 1


async def test_expired_and_tampered_links_are_rejected_by_the_api(api, admin, sent, sessionmaker_):
    _, headers = admin
    await api.post(f"{API}/users/", headers=headers, json={"name": "Fulano", "email": "fulano@example.com"})
    token = _token_from(sent[0])

    tampered = token[:5] + ("x" if token[5] != "x" else "y") + token[6:]
    for path in ("/auth/password/token", "/auth/password/set"):
        r = await api.post(f"{API}{path}", json={"token": tampered, "password": "senha-boa-123x"})
        assert r.status_code == 400 and r.json()["detail"] == "token_invalid"

    async with sessionmaker_() as db:
        await db.execute(update(UserActionToken).values(expires_at=access_service.utcnow() - timedelta(minutes=1)))
        await db.commit()
    r = await api.post(f"{API}/auth/password/set", json={"token": token, "password": "senha-boa-123x"})
    assert r.status_code == 400 and r.json()["detail"] == "token_expired"
    assert (await _get_user(sessionmaker_, "fulano@example.com")).password_hash is None


async def test_invite_existing_user_revokes_provisional_password_and_sessions(api, admin, sent, sessionmaker_):
    """Usuários 9, 10 e 11 de produção: criados à mão com senha provisória e já logados."""
    _, headers = admin
    user = await _add_user(sessionmaker_, "gabriel@example.com", "provisoria1", cargo="Administrador")
    old_jwt = {"Authorization": f"Bearer {create_user_access_token(user)}"}
    assert (await api.get(f"{API}/auth/me", headers=old_jwt)).status_code == 200

    r = await api.post(f"{API}/users/{user.id}/invite", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["invite_pending"] is True and r.json()["invite_email_sent"] is True

    assert (await _login(api, "gabriel@example.com", "provisoria1")).status_code == 401
    assert (await api.get(f"{API}/auth/me", headers=old_jwt)).status_code == 401

    token = _token_from(sent[-1])
    assert (await api.post(f"{API}/auth/password/set", json={"token": token, "password": "gabriel-escolheu"})).status_code == 200
    assert (await _login(api, "gabriel@example.com", "gabriel-escolheu")).status_code == 200


async def test_resend_invite_invalidates_previous_link(api, admin, sent, sessionmaker_):
    _, headers = admin
    created = await api.post(f"{API}/users/", headers=headers, json={"name": "Rafa", "email": "rafa@example.com"})
    first = _token_from(sent[0])
    await api.post(f"{API}/users/{created.json()['id']}/invite", headers=headers)
    second = _token_from(sent[1])
    assert first != second
    r = await api.post(f"{API}/auth/password/token", json={"token": first})
    assert r.status_code == 400 and r.json()["detail"] == "token_invalid"
    assert (await api.post(f"{API}/auth/password/token", json={"token": second})).status_code == 200


async def test_invite_email_failure_keeps_invite_and_reports_it(api, admin, monkeypatch, sessionmaker_):
    _, headers = admin
    monkeypatch.setattr(access_email.email_service, "send_email", lambda **kw: False)
    r = await api.post(f"{API}/users/", headers=headers, json={"name": "Sem Email", "email": "x@example.com"})
    assert r.status_code == 201
    assert r.json()["invite_email_sent"] is False
    async with sessionmaker_() as db:
        assert len((await db.execute(select(UserActionToken))).scalars().all()) == 1


async def test_admin_cannot_invite_self_or_inactive_user(api, admin, sent, sessionmaker_):
    me, headers = admin
    assert (await api.post(f"{API}/users/{me.id}/invite", headers=headers)).status_code == 400
    inactive = await _add_user(sessionmaker_, "off@example.com", "senha-antiga-1", is_active=False)
    assert (await api.post(f"{API}/users/{inactive.id}/invite", headers=headers)).status_code == 400
    assert (await api.post(f"{API}/users/9999/invite", headers=headers)).status_code == 404
    assert sent == []


# ── Esqueci minha senha ─────────────────────────────────────────────────


async def test_forgot_password_answers_the_same_whether_or_not_the_account_exists(api, sent, sessionmaker_):
    await _add_user(sessionmaker_, "existe@example.com", "senha-antiga-1")
    unknown = await api.post(f"{API}/auth/password/forgot", json={"email": "naoexiste@example.com"})
    known = await api.post(f"{API}/auth/password/forgot", json={"email": "Existe@Example.com"})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert [m["to_addrs"] for m in sent] == [["existe@example.com"]]
    assert sent[0]["subject"] == "Redefinir sua senha do SAÍRA"
    assert "1 hora" in sent[0]["text_body"]


async def test_forgot_password_reset_flow_kills_old_sessions_and_notifies(api, sent, sessionmaker_):
    user = await _add_user(sessionmaker_, "maria@example.com", "senha-antiga-1")
    old_jwt = {"Authorization": f"Bearer {create_user_access_token(user)}"}
    await api.post(f"{API}/auth/password/forgot", json={"email": "maria@example.com"})
    token = _token_from(sent[0])

    info = await api.post(f"{API}/auth/password/token", json={"token": token})
    assert info.json()["purpose"] == "reset"
    r = await api.post(f"{API}/auth/password/set", json={"token": token, "password": "senha-nova-maria"})
    assert r.status_code == 200, r.text

    assert (await _login(api, "maria@example.com", "senha-antiga-1")).status_code == 401
    assert (await _login(api, "maria@example.com", "senha-nova-maria")).status_code == 200
    assert (await api.get(f"{API}/auth/me", headers=old_jwt)).status_code == 401
    assert sent[-1]["subject"] == "Sua senha do SAÍRA foi alterada"


async def test_forgot_password_for_inactive_or_invited_user(api, sent, sessionmaker_):
    await _add_user(sessionmaker_, "inativo@example.com", "senha-antiga-1", is_active=False)
    await _add_user(sessionmaker_, "convidado@example.com")  # sem senha: o link de recuperação também serve
    r1 = await api.post(f"{API}/auth/password/forgot", json={"email": "inativo@example.com"})
    r2 = await api.post(f"{API}/auth/password/forgot", json={"email": "convidado@example.com"})
    assert r1.status_code == r2.status_code == 202
    assert [m["to_addrs"] for m in sent] == [["convidado@example.com"]]


async def test_forgot_password_limits_per_email_silently_and_per_ip_with_429(api, sent, sessionmaker_):
    await _add_user(sessionmaker_, "limite@example.com", "senha-antiga-1")
    for _ in range(5):
        r = await api.post(f"{API}/auth/password/forgot", json={"email": "limite@example.com"})
        assert r.status_code == 202
    assert len(sent) == 3  # PASSWORD_FORGOT_MAX_PER_EMAIL_HOUR

    codes = []
    for i in range(6):
        r = await api.post(f"{API}/auth/password/forgot", json={"email": f"outro{i}@example.com"})
        codes.append(r.status_code)
    assert codes[:5] == [202] * 5  # 5 + 5 = 10 pedidos do mesmo IP
    assert codes[5] == 429


async def test_weak_password_is_refused_and_link_stays_usable(api, sent, sessionmaker_):
    await _add_user(sessionmaker_, "fraca@example.com", "senha-antiga-1")
    await api.post(f"{API}/auth/password/forgot", json={"email": "fraca@example.com"})
    token = _token_from(sent[0])
    for weak in ("12345678", "aaaaaaaaaa", "fraca@example.com", "curta"):
        r = await api.post(f"{API}/auth/password/set", json={"token": token, "password": weak})
        assert r.status_code == 422, (weak, r.text)
    r = await api.post(f"{API}/auth/password/set", json={"token": token, "password": "agora-sim-forte"})
    assert r.status_code == 200


# ── Senha provisória e troca logado ─────────────────────────────────────


async def test_admin_set_password_is_provisional_and_blocks_until_changed(api, admin, sent, sessionmaker_):
    _, headers = admin
    r = await api.post(
        f"{API}/users/",
        headers=headers,
        json={"name": "Provisório", "email": "prov@example.com", "password": "provisoria-123", "cargo": "Administrador"},
    )
    assert r.status_code == 201
    assert r.json()["must_change_password"] is True and r.json()["invite_email_sent"] is None
    assert sent == []

    login = await _login(api, "prov@example.com", "provisoria-123")
    assert login.status_code == 200 and login.json()["must_change_password"] is True
    jwt = {"Authorization": f"Bearer {login.json()['access_token']}"}

    blocked = await api.get(f"{API}/users/", headers=jwt)
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"
    me = await api.get(f"{API}/auth/me", headers=jwt)
    assert me.status_code == 200 and me.json()["must_change_password"] is True

    changed = await api.post(
        f"{API}/auth/password/change",
        headers=jwt,
        json={"current_password": "provisoria-123", "new_password": "a-minha-de-verdade"},
    )
    assert changed.status_code == 200, changed.text
    new_jwt = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert (await api.get(f"{API}/users/", headers=new_jwt)).status_code == 200
    assert (await api.get(f"{API}/auth/me", headers=jwt)).status_code == 401  # sessão antiga caiu
    assert sent[-1]["subject"] == "Sua senha do SAÍRA foi alterada"


async def test_admin_patch_password_makes_it_provisional_and_drops_sessions(api, admin, sessionmaker_):
    _, headers = admin
    user = await _add_user(sessionmaker_, "op@example.com", "senha-do-dono-1")
    old_jwt = {"Authorization": f"Bearer {create_user_access_token(user)}"}
    r = await api.patch(f"{API}/users/{user.id}", headers=headers, json={"password": "provisoria-456"})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert (await api.get(f"{API}/auth/me", headers=old_jwt)).status_code == 401


async def test_change_password_wrong_current_is_400_not_401(api, sessionmaker_):
    user = await _add_user(sessionmaker_, "troca@example.com", "senha-atual-1")
    jwt = {"Authorization": f"Bearer {create_user_access_token(user)}"}
    wrong = await api.post(
        f"{API}/auth/password/change", headers=jwt,
        json={"current_password": "errada-errada", "new_password": "senha-nova-boa"},
    )
    assert wrong.status_code == 400
    same = await api.post(
        f"{API}/auth/password/change", headers=jwt,
        json={"current_password": "senha-atual-1", "new_password": "senha-atual-1"},
    )
    assert same.status_code == 422
    assert verify_password("senha-atual-1", (await _get_user(sessionmaker_, "troca@example.com")).password_hash)


async def test_login_is_throttled_after_repeated_failures(api, sessionmaker_):
    await _add_user(sessionmaker_, "alvo@example.com", "senha-certa-123")
    for _ in range(10):
        assert (await _login(api, "alvo@example.com", "errada")).status_code == 401
    blocked = await _login(api, "alvo@example.com", "senha-certa-123")
    assert blocked.status_code == 429
    # Outro e-mail não é afetado
    await _add_user(sessionmaker_, "outro@example.com", "senha-certa-123")
    assert (await _login(api, "outro@example.com", "senha-certa-123")).status_code == 200


async def test_successful_login_resets_failure_counter(api, sessionmaker_):
    await _add_user(sessionmaker_, "zera@example.com", "senha-certa-123")
    for _ in range(9):
        await _login(api, "zera@example.com", "errada")
    assert (await _login(api, "zera@example.com", "senha-certa-123")).status_code == 200
    for _ in range(9):
        await _login(api, "zera@example.com", "errada")
    assert (await _login(api, "zera@example.com", "senha-certa-123")).status_code == 200


# ── E-mails ─────────────────────────────────────────────────────────────


def test_emails_have_html_and_text_and_no_mojibake():
    from datetime import datetime, timezone

    messages = [
        access_email.build_invite_email("Rayssa Lima", "https://x/definir-senha#token=t", "Alexandre"),
        access_email.build_reset_email("Rayssa", "https://x/definir-senha#token=t"),
        access_email.build_password_changed_email("Rayssa", datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)),
    ]
    for subject, html, text in messages:
        assert "SAÍRA" in subject
        assert html.startswith("<html>") and "Olá, Rayssa" in html and "Olá, Rayssa" in text
        for bad in ("Ã", "â€", "�"):
            assert bad not in subject + html + text
    assert "26/11/2026 às 09:00" in messages[2][2]  # horário de Brasília
