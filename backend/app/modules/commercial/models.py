"""Commercial evidence is independent of physical inventory movements."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, deferred

from app.core.database import Base
from app.core.time import utc_now


class CommercialDocument(Base):
    __tablename__ = "commercial_documents"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary))
    extracted_text: Mapped[str | None] = deferred(mapped_column(Text))
    method: Mapped[str] = mapped_column(String(60))
    parser_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CommercialRecord(Base):
    __tablename__ = "commercial_records"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "row_number", name="uq_commercial_document_row"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commercial_documents.id", ondelete="RESTRICT"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    superseded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Original cells never change. Corrections are separate and audited.
    source: Mapped[dict] = mapped_column(JSON)
    corrections: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class CommercialProductProfile(Base):
    __tablename__ = "commercial_product_profiles"
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True
    )
    ean14: Mapped[str | None] = mapped_column(String(14))
    presentation: Mapped[str | None] = mapped_column(String(160))
    content: Mapped[str | None] = mapped_column(String(160))
    line: Mapped[str | None] = mapped_column(String(100))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
