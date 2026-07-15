import uuid
from datetime import datetime
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.core.time import utc_now


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint(
            "delivery_type IN ('without_issue','confirmed','with_issue')",
            name="valid_type",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    delivery_type: Mapped[str] = mapped_column(String(30), nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    recipient: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    registered_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class DeliveryLine(Base):
    __tablename__ = "delivery_lines"
    __table_args__ = (
        CheckConstraint("delivered_quantity >= 0", name="delivered_nonnegative"),
        CheckConstraint("rejected_quantity >= 0", name="rejected_nonnegative"),
        CheckConstraint(
            "delivered_quantity + rejected_quantity > 0", name="reported_positive"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("invoice_lines.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    delivered_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rejected_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
