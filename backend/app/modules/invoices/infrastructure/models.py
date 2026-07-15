import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('purchase_order','sale_without_po','internal_consumption','sample','replacement','other')",
            name="valid_source_type",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_number: Mapped[str] = mapped_column(
        String(17), unique=True, nullable=False, index=True
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    chain_name: Mapped[str | None] = mapped_column(String(160), index=True)
    authorization_number: Mapped[str | None] = mapped_column(String(80))
    remittance_guide: Mapped[str | None] = mapped_column(String(100))
    total_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    administrative_status: Mapped[str] = mapped_column(
        String(20), default="confirmed", nullable=False
    )
    dispatch_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    delivery_status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False
    )
    incident_status: Mapped[str] = mapped_column(
        String(30), default="none", nullable=False
    )
    return_status: Mapped[str] = mapped_column(
        String(30), default="none", nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "product_id", name="uq_invoice_product"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    outside_purchase_order: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class InvoiceAlert(Base):
    __tablename__ = "invoice_alerts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT")
    )
    alert_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
