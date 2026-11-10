"""005_policy_line_match_similarity

Revision ID: 005_policy_line_match_similarity
Revises: 004_policy_approval_gates
Create Date: 2026-11-10 11:00:00.000000

Text-based PO line matching threshold becomes a per-policy setting (default 0.5, the value
previously hardcoded in the matching engine).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005_policy_line_match_similarity"
down_revision: Union[str, None] = "004_policy_approval_gates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tolerance_policies",
        sa.Column(
            "line_description_min_similarity",
            sa.Numeric(6, 4),
            server_default="0.5000",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tolerance_policies", "line_description_min_similarity")
