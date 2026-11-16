"""Store processing artifact keys on receipt jobs.

Revision ID: 0002_processing_artifacts
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_processing_artifacts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipt_jobs",
        sa.Column("ocr_storage_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "receipt_jobs",
        sa.Column("extraction_storage_key", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("receipt_jobs", "extraction_storage_key")
    op.drop_column("receipt_jobs", "ocr_storage_key")
