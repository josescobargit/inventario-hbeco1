import pytest
from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.infrastructure.models import Role, User, UserSession
from scripts.recover_admin_access import reset_existing_admin


@pytest.fixture
def recovery_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Role.__table__,
            User.__table__,
            UserSession.__table__,
            AuditLog.__table__,
        ],
    )
    with Session(engine) as db:
        role = Role(code="principal", name="Principal")
        user = User(
            role=role,
            username="admin",
            full_name="Administrador",
            password_hash=PasswordHash.recommended().hash("Anterior-segura-123"),
        )
        db.add(user)
        db.flush()
        db.add(UserSession(user_id=user.id, token_hash="test", expires_at=utc_now()))
        db.commit()
        yield db
    engine.dispose()


def test_recovery_changes_password_revokes_sessions_and_audits(recovery_db):
    reset_existing_admin(
        recovery_db, " ADMIN ", "Nueva-segura-456", "Acceso recuperado"
    )
    recovery_db.commit()
    user = recovery_db.scalar(select(User))
    assert PasswordHash.recommended().verify("Nueva-segura-456", user.password_hash)
    assert not PasswordHash.recommended().verify(
        "Anterior-segura-123", user.password_hash
    )
    assert recovery_db.scalar(select(UserSession)).revoked_at is not None
    audit = recovery_db.scalar(select(AuditLog))
    assert audit.action == "admin_access_recovered"
    assert "password" not in str(audit.new_value)


@pytest.mark.parametrize(
    "username,password", [("missing", "Nueva-segura-456"), ("admin", "123")]
)
def test_recovery_rejects_missing_user_or_short_password(
    recovery_db, username, password
):
    with pytest.raises(ValueError):
        reset_existing_admin(recovery_db, username, password, "Prueba")
    assert recovery_db.scalar(select(AuditLog)) is None
    assert recovery_db.scalar(select(UserSession)).revoked_at is None


def test_recovery_does_not_grant_admin_or_reactivate_users(recovery_db):
    user = recovery_db.scalar(select(User))
    user.is_active = False
    recovery_db.flush()
    with pytest.raises(ValueError):
        reset_existing_admin(recovery_db, "admin", "Nueva-segura-456", "Prueba")
    assert recovery_db.scalar(select(AuditLog)) is None
