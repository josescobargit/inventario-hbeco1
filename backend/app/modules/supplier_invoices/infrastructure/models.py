import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import utc_now


class SupplierInvoice(Base):
    __tablename__ = "supplier_invoices"
    __table_args__ = (
        UniqueConstraint(
            "supplier_ruc",
            "invoice_number",
            name="uq_supplier_invoice_ruc_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    supplier_ruc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    invoice_number: Mapped[str] = mapped_column(String(17), nullable=False, index=True)
    issued_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    authorization_number: Mapped[str | None] = mapped_column(
        String(60), nullable=True, unique=True
    )
    buyer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    buyer_ruc: Mapped[str | None] = mapped_column(String(13), nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    tax: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="confirmed", nullable=False, index=True
    )
    registered_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    inventory_applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    inventory_reversed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class SupplierInvoiceLine(Base):
    __tablename__ = "supplier_invoice_lines"
    __table_args__ = (
        UniqueConstraint(
            "supplier_invoice_id",
            "line_number",
            name="uq_supplier_invoice_line_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    supplier_invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("supplier_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    discount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)


class SupplierProductAlias(Base):
    __tablename__ = "supplier_product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "supplier_ruc",
            "supplier_code",
            name="uq_supplier_alias_code",
        ),
        UniqueConstraint(
            "supplier_ruc",
            "barcode",
            name="uq_supplier_alias_barcode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    supplier_ruc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    supplier_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    normalized_description: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    confirmed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
