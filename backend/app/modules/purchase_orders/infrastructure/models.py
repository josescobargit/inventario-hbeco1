import uuid
from datetime import date, datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    LargeBinary,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.core.time import utc_now


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint(
            "chain_name", "order_number", name="uq_purchase_order_chain_number"
        ),
        CheckConstraint(
            "status IN ('open','partially_invoiced','completed','cancelled')",
            name="valid_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chain_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(160), index=True)
    order_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    order_date: Mapped[date | None] = mapped_column(Date)
    destination: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(30), default="open", nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    secondary_reference: Mapped[str | None] = mapped_column(String(100))
    local_name: Mapped[str | None] = mapped_column(String(200))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id", "product_id", name="uq_purchase_order_product"
        ),
        CheckConstraint("ordered_quantity > 0", name="ordered_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ordered_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_quantity: Mapped[int | None] = mapped_column(BigInteger)
    original_unit: Mapped[str | None] = mapped_column(String(30))
    units_per_box: Mapped[int | None] = mapped_column(BigInteger)
    conversion_method: Mapped[str | None] = mapped_column(String(40))
    conversion_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    source_page: Mapped[int | None] = mapped_column(BigInteger)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_code: Mapped[str | None] = mapped_column(String(100))
    source_description: Mapped[str | None] = mapped_column(String(300))


class PurchaseOrderSourceDocument(Base):
    __tablename__ = "purchase_order_source_documents"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    upload_token: Mapped[uuid.UUID] = mapped_column(
        Uuid, unique=True, nullable=False, default=uuid.uuid4, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PurchaseOrderDocumentLink(Base):
    __tablename__ = "purchase_order_document_links"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id", "document_id", name="uq_purchase_order_document"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("purchase_order_source_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class CustomerProductAlias(Base):
    __tablename__ = "customer_product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "chain_name_normalized",
            "source_text_normalized",
            name="uq_customer_product_alias",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chain_name: Mapped[str] = mapped_column(String(160), nullable=False)
    chain_name_normalized: Mapped[str] = mapped_column(
        String(160), nullable=False, index=True
    )
    source_text: Mapped[str] = mapped_column(String(300), nullable=False)
    source_text_normalized: Mapped[str] = mapped_column(
        String(300), nullable=False, index=True
    )
    detected_code: Mapped[str | None] = mapped_column(String(100))
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
