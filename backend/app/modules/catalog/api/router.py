import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.api.router import request_metadata
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)


router = APIRouter(prefix="/catalog", tags=["Catálogo"])


class ProductInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str = Field(min_length=2, max_length=100)
    barcode: str | None = Field(default=None, max_length=80)
    contifico_aux_code: str | None = Field(default=None, max_length=80)
    cost: Decimal = Field(ge=0, max_digits=14, decimal_places=4)
    units_per_box: int = Field(gt=0, le=10000)
    is_active: bool = True

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("name", "category")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("description", "barcode", "contifico_aux_code")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductUpdateInput(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str = Field(min_length=2, max_length=100)
    barcode: str | None = Field(default=None, max_length=80)
    contifico_aux_code: str | None = Field(default=None, max_length=80)
    cost: Decimal = Field(ge=0, max_digits=14, decimal_places=4)
    units_per_box: int = Field(gt=0, le=10000)
    is_active: bool = True

    @field_validator("name", "category")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("description", "barcode", "contifico_aux_code")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductResponse(ProductUpdateInput):
    id: uuid.UUID
    sku: str
    created_at: datetime
    updated_at: datetime
    physical_confirmed: int
    reserved: int
    invoiced_not_dispatched: int
    blocked_by_incident: int


def require_principal(user) -> None:
    if user.role.code != "principal":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el usuario principal puede modificar el catálogo.",
        )


def snapshot(product: Product) -> dict:
    return {
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "barcode": product.barcode,
        "contifico_aux_code": product.contifico_aux_code,
        "cost": str(product.cost),
        "units_per_box": product.units_per_box,
        "is_active": product.is_active,
    }


def position_totals(db: Session, product: Product) -> InventoryPositionModel | None:
    return db.scalar(
        select(InventoryPositionModel).where(
            InventoryPositionModel.product_id == product.id
        )
    )


def response_for(
    product: Product, position: InventoryPositionModel | None
) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        category=product.category,
        barcode=product.barcode,
        contifico_aux_code=product.contifico_aux_code,
        cost=product.cost,
        units_per_box=product.units_per_box,
        is_active=product.is_active,
        created_at=product.created_at,
        updated_at=product.updated_at,
        physical_confirmed=position.physical_confirmed if position else 0,
        reserved=position.reserved if position else 0,
        invoiced_not_dispatched=position.invoiced_not_dispatched if position else 0,
        blocked_by_incident=position.blocked_by_incident if position else 0,
    )


def ensure_principal_position(db: Session, product: Product) -> InventoryPositionModel:
    warehouse = db.scalar(select(Warehouse).where(Warehouse.code == "principal"))
    if warehouse is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No existe la bodega principal. Aplica las migraciones.",
        )
    position = db.scalar(
        select(InventoryPositionModel).where(
            InventoryPositionModel.warehouse_id == warehouse.id,
            InventoryPositionModel.product_id == product.id,
        )
    )
    if position is None:
        position = InventoryPositionModel(
            warehouse_id=warehouse.id,
            product_id=product.id,
        )
        db.add(position)
        db.flush()
    return position


@router.get("/products", response_model=list[ProductResponse])
def list_products(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    category: str | None = None,
    active: bool | None = None,
) -> list[ProductResponse]:
    statement = (
        select(Product, InventoryPositionModel)
        .outerjoin(
            InventoryPositionModel, InventoryPositionModel.product_id == Product.id
        )
        .order_by(Product.sku)
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(Product.sku.ilike(term), Product.name.ilike(term))
        )
    if category and category.strip():
        statement = statement.where(Product.category == category.strip())
    if active is not None:
        statement = statement.where(Product.is_active.is_(active))
    return [
        response_for(product, position) for product, position in db.execute(statement)
    ]


@router.get("/categories", response_model=list[str])
def list_categories(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return [
        category
        for category in db.scalars(
            select(Product.category).distinct().order_by(Product.category)
        )
        if category
    ]


@router.post(
    "/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED
)
def create_product(
    payload: ProductInput,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ProductResponse:
    require_principal(user)
    product = Product(**payload.model_dump())
    db.add(product)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un producto con ese SKU.",
        ) from error
    position = ensure_principal_position(db, product)
    ip_address, user_agent = request_metadata(request)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="product_created",
            entity_type="product",
            entity_id=product.sku,
            reason="Producto creado desde catálogo",
            new_value=snapshot(product),
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.commit()
    db.refresh(product)
    db.refresh(position)
    return response_for(product, position)


@router.put("/products/{sku}", response_model=ProductResponse)
def update_product(
    sku: str,
    payload: ProductUpdateInput,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ProductResponse:
    require_principal(user)
    product = db.scalar(select(Product).where(Product.sku == sku.strip().upper()))
    if product is None:
        raise HTTPException(status_code=404, detail="No encontramos ese producto.")
    position = ensure_principal_position(db, product)
    if product.is_active and not payload.is_active:
        open_units = db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        InventoryPositionModel.physical_confirmed
                        + InventoryPositionModel.reserved
                        + InventoryPositionModel.invoiced_not_dispatched
                        + InventoryPositionModel.blocked_by_incident
                    ),
                    0,
                )
            ).where(InventoryPositionModel.product_id == product.id)
        )
        if open_units:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No puedes desactivar un producto con stock o saldos operativos.",
            )
    previous = snapshot(product)
    for field, value in payload.model_dump().items():
        setattr(product, field, value)
    ip_address, user_agent = request_metadata(request)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="product_updated",
            entity_type="product",
            entity_id=product.sku,
            reason="Producto actualizado desde catálogo",
            previous_value=previous,
            new_value=snapshot(product),
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.commit()
    db.refresh(product)
    db.refresh(position)
    return response_for(product, position)
