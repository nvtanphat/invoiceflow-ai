"""003_field_evidence_verification_state

Revision ID: 003_field_evidence_verification_state
Revises: 002_field_evidence_table_cell_provenance
Create Date: 2026-11-09 09:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '003_field_evidence_verification_state'
down_revision: Union[str, None] = '002_field_evidence_table_cell_provenance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'field_evidences',
        sa.Column(
            'verification_state',
            sa.String(length=50),
            server_default='model_proposed',
            nullable=False,
        ),
    )
    op.add_column(
        'field_evidences',
        sa.Column(
            'review_reason',
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('field_evidences', 'review_reason')
    op.drop_column('field_evidences', 'verification_state')
