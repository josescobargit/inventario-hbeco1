"""Operator-only recovery using the configured database, never a public endpoint."""

import argparse
import getpass
import sys

from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.domain.credentials import normalize_username
from app.modules.auth.infrastructure.models import User, UserSession


def reset_existing_admin(
    db: Session, username: str, password: str, reason: str
) -> None:
    if not 12 <= len(password) <= 128:
        raise ValueError("La contraseña debe tener entre 12 y 128 caracteres.")
    if not reason.strip():
        raise ValueError("Indica el motivo de la recuperación.")
    user = db.scalar(
        select(User)
        .where(User.username == normalize_username(username))
        .with_for_update(of=User)
    )
    if user is None:
        raise ValueError("Ese usuario no existe en esta base; no se creó otra cuenta.")
    if user.role.code != "principal" or not user.is_active:
        raise ValueError("Solo se recupera un administrador existente y activo.")
    user.password_hash = PasswordHash.recommended().hash(password)
    user.must_change_password = False
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    db.add(
        AuditLog(
            action="admin_access_recovered",
            entity_type="user",
            entity_id=str(user.id),
            reason=reason.strip(),
            new_value={"username": user.username, "sessions_revoked": True},
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnosticar o recuperar acceso admin."
    )
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--username")
    parser.add_argument("--reason")
    args = parser.parse_args()
    if make_url(str(engine.url)).host != args.expected_host:
        print("La base configurada no coincide con el host esperado; no hubo cambios.")
        return 2
    with SessionLocal.begin() as db:
        if not args.username:
            for user in db.scalars(select(User).order_by(User.username)):
                print(f"{user.username} | {user.role.code} | activo={user.is_active}")
            return 0
        if not args.reason:
            parser.error("La recuperación exige --reason.")
        if not sys.stdin.isatty():
            print("La contraseña debe ingresarse en una terminal interactiva.")
            return 2
        password = getpass.getpass("Nueva contraseña: ")
        if password != getpass.getpass("Repetir contraseña: "):
            print("Las contraseñas no coinciden; no hubo cambios.")
            return 2
        reset_existing_admin(db, args.username, password, args.reason)
    print("Acceso recuperado. Las sesiones anteriores fueron revocadas.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(str(exc))
        sys.exit(2)
