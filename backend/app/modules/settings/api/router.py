from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.api.router import request_metadata
from app.modules.auth.infrastructure.models import User
from app.modules.settings.domain.operational import (
    DEFAULT_OPERATIONAL_SETTINGS,
    OPERATIONAL_KEY,
)
from app.modules.settings.infrastructure.models import AppSetting


router = APIRouter(prefix="/settings", tags=["Configuración"])


class OperationalSettingsInput(BaseModel):
    warehouse_name: str = Field(min_length=2, max_length=120)
    low_stock_threshold_mode: Literal["boxes", "units"] = "boxes"
    low_stock_threshold_boxes: int = Field(ge=0, le=20)
    low_stock_threshold_units: int = Field(ge=0, le=10000)
    report_default_days: int = Field(ge=1, le=365)
    allow_exception_invoices: bool = True
    suggested_chains: list[str] = Field(min_length=1, max_length=20)
    invoice_exception_note: str = Field(min_length=2, max_length=500)

    @field_validator("suggested_chains")
    @classmethod
    def normalize_chains(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            chain = item.strip()
            marker = chain.lower()
            if len(chain) < 2:
                continue
            if marker not in seen:
                normalized.append(chain)
                seen.add(marker)
        if not normalized:
            raise ValueError("Configura al menos una cadena sugerida.")
        return normalized


class OperationalSettingsResponse(OperationalSettingsInput):
    updated_at: datetime | None = None
    updated_by: str | None = None


def require_principal(user) -> None:
    if user.role.code != "principal":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el usuario principal puede modificar la configuración.",
        )


def normalize_payload(value: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_OPERATIONAL_SETTINGS, **(value or {})}
    return OperationalSettingsInput.model_validate(merged).model_dump()


def response_for(
    db: Session, setting: AppSetting | None
) -> OperationalSettingsResponse:
    value = normalize_payload(
        setting.value if setting else DEFAULT_OPERATIONAL_SETTINGS
    )
    updated_by = None
    if setting and setting.updated_by_user_id:
        actor = db.get(User, setting.updated_by_user_id)
        updated_by = actor.full_name if actor else None
    return OperationalSettingsResponse(
        **value,
        updated_at=setting.updated_at if setting else None,
        updated_by=updated_by,
    )


@router.get("/operational", response_model=OperationalSettingsResponse)
def get_operational_settings(
    _user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> OperationalSettingsResponse:
    setting = db.get(AppSetting, OPERATIONAL_KEY)
    return response_for(db, setting)


@router.put("/operational", response_model=OperationalSettingsResponse)
def update_operational_settings(
    payload: OperationalSettingsInput,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> OperationalSettingsResponse:
    require_principal(user)
    setting = db.get(AppSetting, OPERATIONAL_KEY)
    previous_value = setting.value if setting else None
    if setting is None:
        setting = AppSetting(
            key=OPERATIONAL_KEY,
            value=payload.model_dump(),
            description="Parámetros operativos generales del sistema",
            updated_by_user_id=user.id,
        )
        db.add(setting)
    else:
        setting.value = payload.model_dump()
        setting.updated_by_user_id = user.id
    ip_address, user_agent = request_metadata(request)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="settings_updated",
            entity_type="settings",
            entity_id=OPERATIONAL_KEY,
            reason="Actualización de parámetros operativos",
            previous_value=previous_value,
            new_value=payload.model_dump(),
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.commit()
    db.refresh(setting)
    return response_for(db, setting)
