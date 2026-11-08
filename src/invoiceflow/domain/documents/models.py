from enum import Enum
from typing import Any, List, Optional, Union
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
    page_width: Optional[float] = None
    page_height: Optional[float] = None
    rotation: int = 0


class DocumentElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    page_index: int = Field(..., ge=0)
    kind: str = "text"
    text: str
    raw_text: Optional[str] = None
    normalized_text: Optional[str] = None
    bbox: Optional[BoundingBox] = None
    reading_order: int = 0
    parent_id: Optional[str] = None
    confidence: Optional[float] = None


class DocumentCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[str] = None
    table_id: Optional[str] = None
    row_index: int
    col_index: int
    text: str
    raw_text: Optional[str] = None
    normalized_text: Optional[str] = None
    rowspan: int = 1
    colspan: int = 1
    bbox: Optional[BoundingBox] = None
    confidence: Optional[float] = None


class DocumentTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    page_index: int = Field(..., ge=0)
    row_count: int
    column_count: int
    cells: List[DocumentCell] = Field(default_factory=list)
    bbox: Optional[BoundingBox] = None
    confidence: Optional[float] = None


class CanonicalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: Union[UUID, str]
    tenant_id: Union[UUID, str]
    source_format: str
    parser_name: str
    parser_version: str
    config_hash: str
    source_checksum: Optional[str] = None
    page_count: int
    page_rotations: dict[int, int] = Field(default_factory=dict)
    elements: List[DocumentElement] = Field(default_factory=list)
    tables: List[DocumentTable] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
