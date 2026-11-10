"""006_tenant_and_query_indexes

Revision ID: 006_tenant_and_query_indexes
Revises: 005_policy_line_match_similarity
Create Date: 2026-11-10 12:20:00.000000

Adds missing tenant_id single-column and composite query indexes across multi-tenant tables.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006_tenant_and_query_indexes"
down_revision: Union[str, None] = "005_policy_line_match_similarity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_purchase_orders_tenant_id", "purchase_orders", ["tenant_id"])
    op.create_index(
        "ix_purchase_orders_tenant_vendor", "purchase_orders", ["tenant_id", "vendor_tax_id"]
    )
    op.create_index("ix_goods_receipts_tenant_id", "goods_receipts", ["tenant_id"])
    op.create_index("ix_goods_receipts_tenant_po", "goods_receipts", ["tenant_id", "po_id"])
    op.create_index("ix_tolerance_policies_tenant_id", "tolerance_policies", ["tenant_id"])
    op.create_index("ix_match_results_tenant_id", "match_results", ["tenant_id"])
    op.create_index(
        "ix_match_results_tenant_invoice", "match_results", ["tenant_id", "invoice_id"]
    )
    op.create_index("ix_invoices_tenant_status", "invoices", ["tenant_id", "status"])
    op.create_index("ix_invoices_tenant_created_at", "invoices", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_invoices_tenant_created_at", table_name="invoices")
    op.drop_index("ix_invoices_tenant_status", table_name="invoices")
    op.drop_index("ix_match_results_tenant_invoice", table_name="match_results")
    op.drop_index("ix_match_results_tenant_id", table_name="match_results")
    op.drop_index("ix_tolerance_policies_tenant_id", table_name="tolerance_policies")
    op.drop_index("ix_goods_receipts_tenant_po", table_name="goods_receipts")
    op.drop_index("ix_goods_receipts_tenant_id", table_name="goods_receipts")
    op.drop_index("ix_purchase_orders_tenant_vendor", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_tenant_id", table_name="purchase_orders")
