"""002_field_evidence_table_cell_provenance

Revision ID: 002_field_evidence_table_cell_provenance
Revises: 001_initial_schema
Create Date: 2026-11-08 20:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_field_evidence_table_cell_provenance"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Links a field's evidence back to the exact source table/cell it was
    # extracted from, so the PDF viewer and audit trail can trace a line
    # item field to its structural origin, not just a page/bbox.
    op.add_column("field_evidences", sa.Column("table_id", sa.String(length=100), nullable=True))
    op.add_column("field_evidences", sa.Column("cell_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("field_evidences", "cell_id")
    op.drop_column("field_evidences", "table_id")
