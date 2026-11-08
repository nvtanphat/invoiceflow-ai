"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-11-08 11:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tenants & Users & Memberships
    op.create_table(
        'tenants',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'memberships',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, default='viewer'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'user_id', name='uq_tenant_user_membership'),
    )

    # 2. Documents & Processing Jobs
    op.create_table(
        'documents',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('storage_uri', sa.String(length=512), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, default='RECEIVED'),
        sa.Column('page_count', sa.Integer(), nullable=False, default=1),
        sa.Column('uploaded_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_documents_tenant_sha256', 'documents', ['tenant_id', 'sha256'])

    op.create_table(
        'processing_jobs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(length=36), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, default='QUEUED'),
        sa.Column('stage', sa.String(length=50), nullable=False, default='PREFLIGHT'),
        sa.Column('attempt_count', sa.Integer(), nullable=False, default=0),
        sa.Column('max_attempts', sa.Integer(), nullable=False, default=3),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('lease_token', sa.String(length=64), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('request_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_processing_jobs_tenant_status', 'processing_jobs', ['tenant_id', 'status'])

    # 3. Invoices, Lines & Field Evidence
    op.create_table(
        'invoices',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(length=36), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, default=1),
        sa.Column('status', sa.String(length=50), nullable=False, default='RECEIVED'),
        sa.Column('supplier_tax_id', sa.String(length=50), nullable=True),
        sa.Column('supplier_name', sa.String(length=255), nullable=True),
        sa.Column('buyer_tax_id', sa.String(length=50), nullable=True),
        sa.Column('buyer_name', sa.String(length=255), nullable=True),
        sa.Column('invoice_number', sa.String(length=50), nullable=True),
        sa.Column('invoice_series', sa.String(length=50), nullable=True),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=False, default='VND'),
        sa.Column('exchange_rate', sa.Numeric(20, 4), nullable=True),
        sa.Column('subtotal', sa.Numeric(20, 4), nullable=False, default=0),
        sa.Column('discount_total', sa.Numeric(20, 4), nullable=False, default=0),
        sa.Column('tax_total', sa.Numeric(20, 4), nullable=False, default=0),
        sa.Column('amount_payable', sa.Numeric(20, 4), nullable=False, default=0),
        sa.Column('rounding_adjustment', sa.Numeric(20, 4), nullable=False, default=0),
        sa.Column('signature_status', sa.String(length=30), nullable=False, default='not_checked'),
        sa.Column('tax_authority_status', sa.String(length=30), nullable=False, default='not_checked'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_invoices_tenant_supplier_number', 'invoices', ['tenant_id', 'supplier_tax_id', 'invoice_series', 'invoice_number'])

    op.create_table(
        'invoice_lines',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('invoice_id', sa.String(length=36), sa.ForeignKey('invoices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('sku_ref', sa.String(length=100), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('qty', sa.Numeric(20, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(20, 4), nullable=False),
        sa.Column('discount', sa.Numeric(20, 4), nullable=False, default=0),
        sa.Column('tax_rate', sa.Numeric(10, 2), nullable=True),
        sa.Column('tax', sa.Numeric(20, 4), nullable=False, default=0),
        sa.Column('line_amount', sa.Numeric(20, 4), nullable=False),
        sa.Column('po_line_id', sa.String(length=36), nullable=True),
    )

    op.create_table(
        'field_evidences',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('invoice_id', sa.String(length=36), sa.ForeignKey('invoices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_path', sa.String(length=100), nullable=False),
        sa.Column('source_kind', sa.String(length=50), nullable=False),
        sa.Column('page_index', sa.Integer(), nullable=True),
        sa.Column('bbox_json', sa.Text(), nullable=True),
        sa.Column('raw_value', sa.Text(), nullable=True),
        sa.Column('normalized_value', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Numeric(5, 4), nullable=True),
        sa.Column('extractor', sa.String(length=50), nullable=False, default='deterministic'),
    )

    # 4. Purchasing: POs & GRNs
    op.create_table(
        'purchase_orders',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vendor_tax_id', sa.String(length=50), nullable=False),
        sa.Column('vendor_name', sa.String(length=255), nullable=False),
        sa.Column('po_number', sa.String(length=50), nullable=False),
        sa.Column('order_date', sa.Date(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False, default='VND'),
        sa.Column('subtotal', sa.Numeric(20, 4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'purchase_order_lines',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('po_id', sa.String(length=36), sa.ForeignKey('purchase_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('sku', sa.String(length=100), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('ordered_qty', sa.Numeric(20, 4), nullable=False),
        sa.Column('unit_price', sa.Numeric(20, 4), nullable=False),
        sa.Column('line_total', sa.Numeric(20, 4), nullable=False),
    )

    op.create_table(
        'goods_receipts',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('po_id', sa.String(length=36), sa.ForeignKey('purchase_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('grn_number', sa.String(length=50), nullable=False),
        sa.Column('receipt_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'goods_receipt_lines',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('grn_id', sa.String(length=36), sa.ForeignKey('goods_receipts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('po_line_id', sa.String(length=36), sa.ForeignKey('purchase_order_lines.id', ondelete='CASCADE'), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('received_qty', sa.Numeric(20, 4), nullable=False),
        sa.Column('rejected_qty', sa.Numeric(20, 4), nullable=False, default=0),
    )

    # 5. Policies, Matching, Auditing & Reliability
    op.create_table(
        'tolerance_policies',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vendor_tax_id', sa.String(length=50), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, default=1),
        sa.Column('price_tolerance_pct', sa.Numeric(6, 4), nullable=False, default=0.02),
        sa.Column('qty_tolerance_pct', sa.Numeric(6, 4), nullable=False, default=0.00),
        sa.Column('max_amount_delta', sa.Numeric(20, 4), nullable=False, default=50000),
        sa.Column('auto_approve_threshold', sa.Numeric(20, 4), nullable=False, default=10000000),
        sa.Column('separation_of_duties_required', sa.Boolean(), nullable=False, default=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'match_results',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('invoice_id', sa.String(length=36), sa.ForeignKey('invoices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('is_matched', sa.Boolean(), nullable=False, default=False),
        sa.Column('requires_review', sa.Boolean(), nullable=False, default=True),
        sa.Column('issues_json', sa.Text(), nullable=False, default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('actor_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('aggregate_type', sa.String(length=100), nullable=False),
        sa.Column('aggregate_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('details_json', sa.Text(), nullable=False, default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('operation', sa.String(length=100), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=False),
        sa.Column('response_body_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'operation', 'idempotency_key', name='uq_tenant_op_idempotency'),
    )

    op.create_table(
        'outbox_events',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('topic', sa.String(length=100), nullable=False),
        sa.Column('aggregate_id', sa.String(length=36), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False, default=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('outbox_events')
    op.drop_table('idempotency_keys')
    op.drop_table('audit_logs')
    op.drop_table('match_results')
    op.drop_table('tolerance_policies')
    op.drop_table('goods_receipt_lines')
    op.drop_table('goods_receipts')
    op.drop_table('purchase_order_lines')
    op.drop_table('purchase_orders')
    op.drop_table('field_evidences')
    op.drop_table('invoice_lines')
    op.drop_table('invoices')
    op.drop_table('processing_jobs')
    op.drop_table('documents')
    op.drop_table('memberships')
    op.drop_table('users')
    op.drop_table('tenants')
