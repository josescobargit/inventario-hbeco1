from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User


router = APIRouter(prefix="/audit", tags=["Historial"])


ACTION_LABELS = {
    "principal_bootstrapped": "Usuario principal creado",
    "user_created": "Usuario creado",
    "login_succeeded": "Inicio de sesión",
    "login_failed": "Inicio fallido",
    "logout": "Cierre de sesión",
    "purchase_order_created": "OC registrada",
    "purchase_order_updated": "OC actualizada",
    "invoice_registered": "Factura registrada",
    "dispatch_confirmed": "Despacho confirmado",
    "delivery_registered": "Entrega registrada",
    "reservation_created": "Reserva creada",
    "reservation_released": "Reserva liberada",
    "stock_adjustment_requested": "Ajuste solicitado",
    "stock_adjustment_approved": "Ajuste aprobado",
    "stock_adjustment_rejected": "Ajuste rechazado",
    "stock_import_persisted": "Carga masiva registrada",
    "inventory_entry_registered": "Entrada registrada",
    "inventory_exit_registered": "Salida registrada",
    "incident_resolved": "Incidencia resuelta",
    "return_registered": "Devolución registrada",
    "invoice_adjustment_registered": "Documento vinculado",
    "settings_updated": "Configuración actualizada",
    "product_created": "Producto creado",
    "product_updated": "Producto actualizado",
}

ENTITY_LABELS = {
    "user": "Usuarios",
    "session": "Sesión",
    "purchase_order": "Órdenes de compra",
    "invoice": "Facturación",
    "dispatch": "Despachos",
    "delivery": "Entregas",
    "reservation": "Reservas",
    "stock_adjustment": "Ajustes",
    "stock_import": "Carga masiva",
    "inventory_operation": "Inventario",
    "incident": "Incidencias",
    "return": "Devoluciones",
    "invoice_adjustment": "Facturación",
    "settings": "Configuración",
    "product": "Catálogo",
}


def label_action(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("_", " ").title())


def label_entity(entity_type: str) -> str:
    return ENTITY_LABELS.get(entity_type, entity_type.replace("_", " ").title())


def summarize_value(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    preferred_keys = [
        "number",
        "invoice",
        "document",
        "chain",
        "sku",
        "products",
        "units",
        "reported_units",
        "delivered_units",
        "rejected_units",
        "type",
        "status",
    ]
    parts = []
    for key in preferred_keys:
        if key in value and value[key] is not None:
            parts.append(f"{key}: {value[key]}")
    if parts:
        return " · ".join(parts[:5])
    return " · ".join(f"{key}: {value[key]}" for key in list(value.keys())[:4])


def serialize(item: AuditLog, user: User | None) -> dict[str, Any]:
    return {
        "id": item.id,
        "occurred_at": item.occurred_at,
        "actor": user.full_name if user else "Sistema",
        "username": user.username if user else None,
        "action": item.action,
        "action_label": label_action(item.action),
        "entity_type": item.entity_type,
        "module": label_entity(item.entity_type),
        "entity_id": item.entity_id,
        "reason": item.reason,
        "summary": summarize_value(item.new_value)
        or summarize_value(item.previous_value),
        "previous_value": item.previous_value,
        "new_value": item.new_value,
        "ip_address": item.ip_address,
    }


@router.get("/history")
def list_history(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=120)] = None,
    actor: Annotated[str | None, Query(max_length=120)] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    module: Annotated[str | None, Query(max_length=80)] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=300)] = 150,
) -> list[dict[str, Any]]:
    statement = (
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                AuditLog.action.ilike(term),
                AuditLog.entity_type.ilike(term),
                AuditLog.entity_id.ilike(term),
                AuditLog.reason.ilike(term),
                User.full_name.ilike(term),
                User.username.ilike(term),
            )
        )
    if actor and actor.strip():
        statement = statement.where(User.full_name.ilike(f"%{actor.strip()}%"))
    if action and action.strip():
        statement = statement.where(AuditLog.action == action.strip())
    if module and module.strip():
        statement = statement.where(AuditLog.entity_type == module.strip())
    if date_from:
        statement = statement.where(AuditLog.occurred_at >= date_from)
    if date_to:
        statement = statement.where(AuditLog.occurred_at <= date_to)
    return [serialize(item, user) for item, user in db.execute(statement).all()]
