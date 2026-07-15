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


class Dispatch(Base):
    __tablename__ = "dispatches"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    responsible_name: Mapped[str] = mapped_column(String(160), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    confirmed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class DispatchLine(Base):
    __tablename__ = "dispatch_lines"
    __table_args__ = (
        CheckConstraint("dispatched_quantity >= 0", name="dispatched_nonnegative"),
        CheckConstraint("missing_quantity >= 0", name="missing_nonnegative"),
        CheckConstraint(
            "dispatched_quantity + missing_quantity > 0", name="reported_positive"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dispatch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("dispatches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("invoice_lines.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dispatched_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    missing_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    missing_reason: Mapped[str | None] = mapped_column(Text)
