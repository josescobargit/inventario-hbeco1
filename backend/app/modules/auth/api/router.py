import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser, hash_session_token
from app.modules.auth.api.schemas import (
    AdminUserResponse,
    BootstrapRequest,
    BootstrapStatusResponse,
    CreateUserRequest,
    LoginRequest,
    UserResponse,
)
from app.modules.auth.infrastructure.models import Role, User, UserSession


router = APIRouter(prefix="/auth", tags=["Autenticación"])
password_hash = PasswordHash.recommended()
settings = get_settings()
DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password-used-only-for-timing-safety")


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role.code,
        must_change_password=user.must_change_password,
    )


def admin_user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role.code,
        role_name=user.role.name,
        must_change_password=user.must_change_password,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def require_principal(user: User) -> None:
    if user.role.code != "principal":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el usuario principal puede administrar usuarios.",
        )


def request_metadata(request: Request) -> tuple[str | None, str | None]:
    ip_address = request.client.host if request.client else None
    return ip_address, request.headers.get("user-agent")


@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(
    db: Annotated[Session, Depends(get_db)],
) -> BootstrapStatusResponse:
    return BootstrapStatusResponse(required=db.scalar(select(func.count(User.id))) == 0)


@router.post(
    "/bootstrap", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def bootstrap_principal(
    payload: BootstrapRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    if db.scalar(select(func.count(User.id))) != 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El usuario principal ya fue creado.",
        )

    principal_role = db.scalar(select(Role).where(Role.code == "principal"))
    if principal_role is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base todavía no está preparada. Aplica las migraciones.",
        )

    user = User(
        role_id=principal_role.id,
        username=payload.username,
        email=str(payload.email).lower() if payload.email else None,
        full_name=payload.full_name.strip(),
        password_hash=password_hash.hash(payload.password),
    )
    db.add(user)
    db.flush()
    ip_address, user_agent = request_metadata(request)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="principal_bootstrapped",
            entity_type="user",
            entity_id=str(user.id),
            reason="Configuración inicial del sistema",
            new_value={"username": user.username, "role": "principal"},
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.commit()
    db.refresh(user)
    return user_response(user)


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    candidate_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_is_valid = password_hash.verify(payload.password, candidate_hash)
    if user is None or not user.is_active or not password_is_valid:
        ip_address, user_agent = request_metadata(request)
        db.add(
            AuditLog(
                action="login_failed",
                entity_type="session",
                entity_id=payload.username,
                reason="Credenciales inválidas o usuario inactivo",
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos.",
        )

    raw_token = secrets.token_urlsafe(48)
    now = utc_now()
    ip_address, user_agent = request_metadata(request)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(raw_token),
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="login_succeeded",
            entity_type="session",
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.commit()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_ttl_hours * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    return user_response(user)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return user_response(user)


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    users = db.scalars(select(User).order_by(User.created_at.asc())).all()
    return [admin_user_response(user) for user in users]


@router.post(
    "/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED
)
def create_user(
    payload: CreateUserRequest,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AdminUserResponse:
    require_principal(user)
    if db.scalar(select(User).where(User.username == payload.username)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario con ese nombre de acceso.",
        )
    normalized_email = str(payload.email).lower() if payload.email else None
    if normalized_email and db.scalar(
        select(User).where(User.email == normalized_email)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario con ese correo.",
        )
    role = db.scalar(select(Role).where(Role.code == payload.role))
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol seleccionado no existe.",
        )

    created_user = User(
        role_id=role.id,
        username=payload.username,
        email=normalized_email,
        full_name=payload.full_name.strip(),
        password_hash=password_hash.hash(payload.password),
    )
    db.add(created_user)
    db.flush()
    ip_address, user_agent = request_metadata(request)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="user_created",
            entity_type="user",
            entity_id=str(created_user.id),
            reason="Usuario creado desde administración",
            new_value={
                "username": created_user.username,
                "full_name": created_user.full_name,
                "role": role.code,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.commit()
    db.refresh(created_user)
    return admin_user_response(created_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == hash_session_token(raw_token),
                UserSession.revoked_at.is_(None),
            )
        )
        if session:
            session.revoked_at = utc_now()
    ip_address, user_agent = request_metadata(request)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="logout",
            entity_type="session",
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
