import uuid
from datetime import datetime
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.core.time import utc_now


class StockImport(Base):
    __tablename__ = "stock_imports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','obsolete')",
            name="valid_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StockImportLine(Base):
    __tablename__ = "stock_import_lines"
    __table_args__ = (
        UniqueConstraint(
            "stock_import_id", "product_id", name="uq_stock_import_product"
        ),
        CheckConstraint(
            "previous_physical_confirmed >= 0", name="previous_nonnegative"
        ),
        CheckConstraint("counted_physical_confirmed >= 0", name="counted_nonnegative"),
        CheckConstraint("position_version > 0", name="version_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    stock_import_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("stock_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    previous_physical_confirmed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    counted_physical_confirmed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position_version: Mapped[int] = mapped_column(Integer, nullable=False)
