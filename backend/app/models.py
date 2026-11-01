import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_auth_identities_issuer_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_code: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductCodeCandidate(Base):
    __tablename__ = "product_code_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved')",
            name="ck_product_code_candidates_status",
        ),
        CheckConstraint(
            "resolution_type IS NULL OR resolution_type IN "
            "('accepted_as_is', 'edited_code', 'mapped_existing')",
            name="ck_product_code_candidates_resolution_type",
        ),
        CheckConstraint(
            "(status = 'pending' AND canonical_product_id IS NULL "
            "AND resolution_type IS NULL AND reviewed_by_id IS NULL "
            "AND reviewed_at IS NULL) OR "
            "(status = 'resolved' AND canonical_product_id IS NOT NULL "
            "AND resolution_type IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_product_code_candidates_resolution_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    observed_code: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_code: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    canonical_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT")
    )
    resolution_type: Mapped[str | None] = mapped_column(String(30))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'queued', 'processing', 'needs_review', "
            "'complete', 'failed')",
            name="ck_receipts_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    retailer_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("retailers.id", ondelete="RESTRICT"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    receipt_number: Mapped[str | None] = mapped_column(String(100))
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default=text("'PLN'")
    )
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    total_paid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploaded", server_default=text("'uploaded'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ReceiptItem(Base):
    __tablename__ = "receipt_items"
    __table_args__ = (
        UniqueConstraint("receipt_id", "line_number", name="uq_receipt_items_line"),
        CheckConstraint("quantity > 0", name="ck_receipt_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_product_code: Mapped[str] = mapped_column(String(500), nullable=False)
    product_code_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_code_candidates.id", ondelete="SET NULL")
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL")
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, default=Decimal("1"), server_default=text("1")
    )
    unit: Mapped[str | None] = mapped_column(String(32))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReceiptJob(Base):
    __tablename__ = "receipt_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed')",
            name="ck_receipt_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_receipt_jobs_attempts_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    stage: Mapped[str | None] = mapped_column(String(30))
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
