from datetime import date, datetime, timezone
from decimal import Decimal
import uuid
from typing import Optional
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from invoiceflow.infrastructure.database.base import Base, TimestampMixin


class TenantORM(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class UserORM(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MembershipORM(Base, TimestampMixin):
    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")

    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user_membership"),)


class DocumentORM(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="RECEIVED", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_documents_tenant_sha256", "tenant_id", "sha256"),)


class ProcessingJobORM(Base, TimestampMixin):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="QUEUED", nullable=False)
    stage: Mapped[str] = mapped_column(String(50), default="PREFLIGHT", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lease_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    request_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_processing_jobs_tenant_status", "tenant_id", "status"),)


class InvoiceORM(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="RECEIVED", nullable=False)

    supplier_tax_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_tax_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    buyer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    invoice_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    invoice_series: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="VND", nullable=False)
    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4), nullable=True)

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0.0000"), nullable=False
    )
    discount_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0.0000"), nullable=False
    )
    tax_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0.0000"), nullable=False
    )
    amount_payable: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0.0000"), nullable=False
    )
    rounding_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0.0000"), nullable=False
    )

    signature_status: Mapped[str] = mapped_column(String(30), default="not_checked", nullable=False)
    tax_authority_status: Mapped[str] = mapped_column(
        String(30), default="not_checked", nullable=False
    )

    lines: Mapped[list["InvoiceLineORM"]] = relationship(
        "InvoiceLineORM", back_populates="invoice", cascade="all, delete-orphan"
    )
    evidence: Mapped[list["FieldEvidenceORM"]] = relationship(
        "FieldEvidenceORM", back_populates="invoice", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_invoices_tenant_supplier_number",
            "tenant_id",
            "supplier_tax_id",
            "invoice_series",
            "invoice_number",
        ),
    )


class InvoiceLineORM(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0.0000"), nullable=False
    )
    tax_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    tax: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0.0000"), nullable=False)
    line_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    po_line_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    invoice: Mapped["InvoiceORM"] = relationship("InvoiceORM", back_populates="lines")


class FieldEvidenceORM(Base):
    __tablename__ = "field_evidences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_path: Mapped[str] = mapped_column(String(100), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    page_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    table_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cell_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    extractor: Mapped[str] = mapped_column(String(50), default="deterministic", nullable=False)
    verification_state: Mapped[str] = mapped_column(
        String(50), default="model_proposed", nullable=False
    )

    invoice: Mapped["InvoiceORM"] = relationship("InvoiceORM", back_populates="evidence")


class PurchaseOrderORM(Base, TimestampMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_tax_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    po_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="VND", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)

    lines: Mapped[list["PurchaseOrderLineORM"]] = relationship(
        "PurchaseOrderLineORM", back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLineORM(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    po_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ordered_qty: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)

    purchase_order: Mapped["PurchaseOrderORM"] = relationship(
        "PurchaseOrderORM", back_populates="lines"
    )


class GoodsReceiptORM(Base, TimestampMixin):
    __tablename__ = "goods_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    po_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    grn_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)

    lines: Mapped[list["GoodsReceiptLineORM"]] = relationship(
        "GoodsReceiptLineORM", back_populates="goods_receipt", cascade="all, delete-orphan"
    )


class GoodsReceiptLineORM(Base):
    __tablename__ = "goods_receipt_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grn_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    po_line_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("purchase_order_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    received_qty: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    rejected_qty: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("0.0000"), nullable=False
    )

    goods_receipt: Mapped["GoodsReceiptORM"] = relationship(
        "GoodsReceiptORM", back_populates="lines"
    )


class TolerancePolicyORM(Base, TimestampMixin):
    __tablename__ = "tolerance_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_tax_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    price_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("0.0200"), nullable=False
    )
    qty_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("0.0000"), nullable=False
    )
    max_amount_delta: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("50000.0000"), nullable=False
    )
    auto_approve_threshold: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), default=Decimal("10000000.0000"), nullable=False
    )
    separation_of_duties_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)


class MatchResultORM(Base, TimestampMixin):
    __tablename__ = "match_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    is_matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    issues_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class IdempotencyKeyORM(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "operation", "idempotency_key", name="uq_tenant_op_idempotency"
        ),
    )


class OutboxEventORM(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
