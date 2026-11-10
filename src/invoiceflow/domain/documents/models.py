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

    def reading_order_text(self) -> str:
        """All recognised text, table rows included, top-to-bottom per page.

        Layout analysis moves table regions out of the text elements; totals and labels
        printed inside such regions must still be visible to text-based field extraction.
        """
        blocks: list[tuple[int, float, float, str]] = []
        for element in self.elements:
            if element.text.strip():
                blocks.append(_block_key(element.page_index, element.bbox, element.text))
        for table in self.tables:
            rows: dict[int, list[DocumentCell]] = {}
            seen: set[int] = set()
            for cell in table.cells:
                if id(cell) in seen or not cell.text.strip():
                    continue
                seen.add(id(cell))
                rows.setdefault(cell.row_index, []).append(cell)
            for cells in rows.values():
                cells.sort(key=lambda c: c.col_index)
                anchor = min(
                    (c for c in cells if c.bbox is not None),
                    key=lambda c: (c.bbox.y0, c.bbox.x0) if c.bbox else (0.0, 0.0),
                    default=None,
                )
                text = " ".join(c.text.strip() for c in cells)
                blocks.append(_block_key(table.page_index, anchor.bbox if anchor else None, text))
        blocks.sort(key=lambda block: block[:3])
        return "\n".join(block[3] for block in blocks)


def _block_key(
    page_index: int, bbox: Optional[BoundingBox], text: str
) -> tuple[int, float, float, str]:
    if bbox is None:
        return page_index, 0.0, 0.0, text.strip()
    return page_index, bbox.y0, bbox.x0, text.strip()
