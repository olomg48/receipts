"""Create initial receipt, product review, identity, and job schema.

Revision ID: 0001_initial
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=300), nullable=False),
        sa.Column("normalized_code", sa.String(length=300), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_code"),
    )
    op.create_table(
        "retailers",
        sa.Column("id", sa.SmallInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "auth_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_auth_identities_issuer_subject"),
    )
    op.create_table(
        "product_code_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_code", sa.String(length=300), nullable=False),
        sa.Column("normalized_code", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("canonical_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_type", sa.String(length=30), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved')",
            name="ck_product_code_candidates_status",
        ),
        sa.CheckConstraint(
            "resolution_type IS NULL OR resolution_type IN "
            "('accepted_as_is', 'edited_code', 'mapped_existing')",
            name="ck_product_code_candidates_resolution_type",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND canonical_product_id IS NULL "
            "AND resolution_type IS NULL AND reviewed_by_id IS NULL "
            "AND reviewed_at IS NULL) OR "
            "(status = 'resolved' AND canonical_product_id IS NOT NULL "
            "AND resolution_type IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_product_code_candidates_resolution_state",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_product_id"], ["products.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_code"),
    )
    op.create_table(
        "receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retailer_id", sa.SmallInteger(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("receipt_number", sa.String(length=100), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'PLN'"), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("discount_total", sa.Numeric(precision=12, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("total_paid", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'uploaded'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('uploaded', 'queued', 'processing', 'needs_review', 'complete', 'failed')",
            name="ck_receipts_status",
        ),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_table(
        "receipt_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("raw_product_code", sa.String(length=500), nullable=False),
        sa.Column("product_code_candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), server_default=sa.text("1"), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(precision=12, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_receipt_items_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["product_code_candidate_id"],
            ["product_code_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", "line_number", name="uq_receipt_items_line"),
    )
    op.create_table(
        "receipt_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed')",
            name="ck_receipt_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_receipt_jobs_attempts_nonnegative"),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    retailers = sa.table(
        "retailers",
        sa.column("id", sa.SmallInteger()),
        sa.column("code", sa.String()),
        sa.column("display_name", sa.String()),
    )
    op.bulk_insert(
        retailers,
        [
            {"id": 1, "code": "biedronka", "display_name": "Biedronka"},
            {"id": 2, "code": "lidl", "display_name": "Lidl"},
        ],
    )
    op.create_index("ix_receipt_jobs_ready", "receipt_jobs", ["status", "available_at"])
    op.create_index("ix_receipt_items_product_id", "receipt_items", ["product_id"])
    op.create_index(
        "ix_receipt_items_candidate_id", "receipt_items", ["product_code_candidate_id"]
    )
    op.create_index("ix_receipts_uploaded_by_id", "receipts", ["uploaded_by_id"])
    op.create_index(
        "ix_product_candidates_review_queue",
        "product_code_candidates",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_candidates_review_queue", table_name="product_code_candidates"
    )
    op.drop_index("ix_receipts_uploaded_by_id", table_name="receipts")
    op.drop_index("ix_receipt_items_candidate_id", table_name="receipt_items")
    op.drop_index("ix_receipt_items_product_id", table_name="receipt_items")
    op.drop_index("ix_receipt_jobs_ready", table_name="receipt_jobs")
    op.drop_table("receipt_jobs")
    op.drop_table("receipt_items")
    op.drop_table("receipts")
    op.drop_table("product_code_candidates")
    op.drop_table("auth_identities")
    op.drop_table("retailers")
    op.drop_table("products")
    op.drop_table("users")
