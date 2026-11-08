from enum import Enum
from typing import Any, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class DocumentKind(str, Enum):
    XML = "xml"
    PDF_DIGITAL = "pdf_digital"
    PDF_SCAN = "pdf_scan"
    IMAGE = "image"
    UNKNOWN = "unknown"


class DocumentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    INSPECTING = "INSPECTING"
    PARSING = "PARSING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    MATCHING = "MATCHING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    RETRY_WAIT = "RETRY_WAIT"


class CoordinateSystem(str, Enum):
    PDF_POINTS = "pdf_points"
    NORMALIZED_0_1000 = "normalized_0_1000"
    PIXELS = "pixels"


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_index: int = Field(..., ge=0, description="0-based page index")
    x0: float
    y0: float
    x1: float
    y1: float
    coordinate_system: CoordinateSystem = CoordinateSystem.PDF_POINTS


class DocumentElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    page_index: int = Field(..., ge=0)
    kind: str = "text"
    text: str
    bbox: Optional[BoundingBox] = None
    reading_order: int = 0
    confidence: Optional[float] = None


class DocumentCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int
    col_index: int
    text: str
    rowspan: int = 1
    colspan: int = 1
    bbox: Optional[BoundingBox] = None


class DocumentTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    page_index: int = Field(..., ge=0)
    row_count: int
    column_count: int
    cells: List[DocumentCell] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    tenant_id: UUID
    source_format: str
    parser_name: str
    parser_version: str
    config_hash: str
    page_count: int
    elements: List[DocumentElement] = Field(default_factory=list)
    tables: List[DocumentTable] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
