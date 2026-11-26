from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.api.deps import get_db, require_admin
from app.core.security import get_password_hash
from app.core.roles import Role, role_from_cargo
from app.models.user import User
from app.core.password_policy import password_problem
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserWithInviteResponse
from app.services import access_email, access_service

router = APIRouter()


def is_admin_cargo(cargo: Optional[str]) -> bool:
    return role_from_cargo(cargo) is Role.ADMIN

USER_SORTABLE_FIELDS: dict[str, Any] = {
    "name":       User.name,
    "email":      User.email,
    "cargo":      User.cargo,
    "rpa":        User.rpa,
    "is_active":  User.is_active,
    "created_at": User.created_at,
}
USER_DEFAULT_SORT = "created_at"


@router.get("/", response_model=List[UserResponse])
async def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    q: Optional[str] = None,
    search: Optional[str] = None,
    rpa: Optional[str] = None,
    cargo: Optional[str] = None,
    is_active: Optional[bool] = None,
    sort_by: Optional[str] = Query(None, description="Campo para ordenação"),
    sort_order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Lista usuários com filtros e paginação"""
    query = select(User)

    filters = []

    # Filtro de busca por nome ou email (q ou search)
    search_term = q or search
    if search_term:
        search_filter = or_(
            User.name.ilike(f"%{search_term}%"),
            User.email.ilike(f"%{search_term}%")
        )
        filters.append(search_filter)

    if rpa:
        filters.append(User.rpa == rpa)
    if cargo:
        filters.append(User.cargo == cargo)
    if is_active is not None:
        filters.append(User.is_active == is_active)

    if filters:
        query = query.where(and_(*filters))

    col = USER_SORTABLE_FIELDS.get(sort_by or USER_DEFAULT_SORT, User.created_at)
    order = col.asc() if sort_order == "asc" else col.desc()
    query = query.offset(skip).limit(limit).order_by(order)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Busca um usuário por ID"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return user


async def _send_invite(db: AsyncSession, user: User, admin: User) -> bool:
    """Grava um link de convite novo (os anteriores caem) e manda o e-mail.

    O commit vem antes do envio: se o e-mail falhar, o convite continua no banco
    e o administrador só precisa reenviar.
    """
    raw = await access_service.issue_token(db, user, access_service.PURPOSE_INVITE, created_by=admin)
    await db.commit()
    return await run_in_threadpool(
        access_email.send_invite, user, access_service.password_link(raw), admin.name
    )


def _reject_weak(password: str, email: str) -> None:
    problem = password_problem(password, email)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)


@router.post("/", response_model=UserWithInviteResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Cria um novo usuário.

    Sem `password` (o normal): nasce com convite pendente e recebe o link por
    e-mail para criar a própria senha. Com `password`: a senha é provisória e o
    dono é obrigado a trocá-la no primeiro login.
    """
    # Verificar se email já existe
    result = await db.execute(select(User).where(User.email == user_in.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    if user_in.password is not None:
        _reject_weak(user_in.password, user_in.email)

    db_user = User(
        name=user_in.name,
        email=user_in.email,
        phone=user_in.phone,
        secretaria=user_in.secretaria,
        cargo=user_in.cargo,
        rpa=user_in.rpa,
        password_hash=get_password_hash(user_in.password) if user_in.password is not None else None,
        must_change_password=user_in.password is not None,
        token_version=0,
        is_active=user_in.is_active
    )

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    sent = None
    if user_in.password is None and user_in.send_invite and db_user.is_active:
        sent = await _send_invite(db, db_user, current_user)

    return UserWithInviteResponse.model_validate(db_user).model_copy(update={"invite_email_sent": sent})


@router.post("/{user_id}/invite", response_model=UserWithInviteResponse)
async def invite_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Envia (ou reenvia) o convite para a pessoa criar a própria senha.

    A senha atual deixa de valer e as sessões abertas caem: ela foi escolhida
    por outra pessoa (senha provisória) e quem a conhece não pode se adiantar
    ao dono. Os links de convite anteriores também deixam de valer.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Para trocar a sua própria senha, use \"Trocar senha\".",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário inativo: reative antes de enviar o convite.",
        )

    access_service.revoke_password_for_invite(user)
    sent = await _send_invite(db, user, current_user)
    return UserWithInviteResponse.model_validate(user).model_copy(update={"invite_email_sent": sent})


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Atualiza um usuário"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Se estiver atualizando email, verificar se já existe
    if user_update.email and user_update.email != user.email:
        result = await db.execute(select(User).where(User.email == user_update.email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

    # Atualizar campos
    update_data = user_update.model_dump(exclude_unset=True)

    # O administrador não tira o próprio acesso: sem isso, o último
    # administrador se trancaria para fora e só o banco resolveria.
    if user.id == current_user.id:
        loses_role = "cargo" in update_data and not is_admin_cargo(update_data["cargo"])
        deactivates = update_data.get("is_active") is False
        if loses_role or deactivates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrador não pode remover o próprio acesso",
            )

    # Senha definida pelo administrador é provisória: o dono troca no 1º
    # login, e as sessões e os links pendentes dele caem.
    if "password" in update_data:
        password = update_data.pop("password")
        if password is not None:
            _reject_weak(password, update_data.get("email") or user.email)
            update_data["password_hash"] = get_password_hash(password)
            if user.id != current_user.id:
                update_data["must_change_password"] = True
                update_data["token_version"] = int(user.token_version or 0) + 1
            await access_service.drop_pending_tokens(db, user.id)

    for key, value in update_data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Deleta um usuário"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrador não pode apagar o próprio usuário",
        )

    await db.delete(user)
    await db.commit()

    return None
