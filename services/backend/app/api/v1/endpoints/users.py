from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.api.deps import get_db, require_admin
from app.core.security import get_password_hash
from app.core.roles import Role, role_from_cargo
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, UserResponse

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


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Cria um novo usuário"""
    # Verificar se email já existe
    result = await db.execute(select(User).where(User.email == user_in.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Criar novo usuário
    password_hash = get_password_hash(user_in.password)
    db_user = User(
        name=user_in.name,
        email=user_in.email,
        phone=user_in.phone,
        secretaria=user_in.secretaria,
        cargo=user_in.cargo,
        rpa=user_in.rpa,
        password_hash=password_hash,
        is_active=user_in.is_active
    )

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    return db_user


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

    # Se houver senha, hashear
    if "password" in update_data:
        password = update_data.pop("password")
        update_data["password_hash"] = get_password_hash(password)

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
