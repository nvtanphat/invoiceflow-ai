"""007_export_batches_and_duplicate_constraints

Revision ID: 007_export_batches_and_duplicate_constraints
Revises: 006_tenant_and_query_indexes
Create Date: 2026-11-10 12:35:00.000000

Adds export_batches table for durable export receipts and partial unique index
on invoices to prevent concurrent duplicate approved/exported invoices.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007_export_batches_and_duplicate_constraints"
down_revision: Union[str, None] = "006_tenant_and_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "export_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("batch_number", sa.String(50), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("invoice_count", sa.Integer(), nullable=False),
        sa.Column(
            "total_amount",
            sa.Numeric(20, 4),
            server_default="0.0000",
            nullable=False,
        ),
        sa.Column("invoice_ids_json", sa.Text(), nullable=False),
        sa.Column("content_base64", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_export_batches_tenant_id", "export_batches", ["tenant_id"])
    op.create_index("ix_export_batches_sha256", "export_batches", ["sha256"])

    op.execute(
        """
        CREATE UNIQUE INDEX uq_invoices_approved_exported
        ON invoices (tenant_id, supplier_tax_id, COALESCE(invoice_series, ''), invoice_number)
        WHERE status IN ('APPROVED', 'EXPORTED')
          AND supplier_tax_id IS NOT NULL
          AND invoice_number IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_invoices_approved_exported;")
    op.drop_index("ix_export_batches_sha256", table_name="export_batches")
    op.drop_index("ix_export_batches_tenant_id", table_name="export_batches")
    op.drop_table("export_batches")
