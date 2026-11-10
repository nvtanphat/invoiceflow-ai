"""004_policy_approval_gates

Revision ID: 004_policy_approval_gates
Revises: 003_field_evidence_verification_state
Create Date: 2026-11-10 09:00:00.000000

Adds explicit approval-gate policy switches. Existing tenants keep the safe default:
no system auto-approval, purchase order and goods receipt required.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_policy_approval_gates"
down_revision: Union[str, None] = "003_field_evidence_verification_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tolerance_policies",
        sa.Column("auto_approval_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "tolerance_policies",
        sa.Column("po_required", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "tolerance_policies",
        sa.Column("goods_receipt_required", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tolerance_policies", "goods_receipt_required")
    op.drop_column("tolerance_policies", "po_required")
    op.drop_column("tolerance_policies", "auto_approval_enabled")
