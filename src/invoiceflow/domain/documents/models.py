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
        """All recognised text as visual lines, top-to-bottom and left-to-right per page.

        Layout analysis moves table regions out of the text elements, and OCR often splits a
        label and its amount into separate blocks on the same printed line. Text-based field
        extraction needs both back together, so table cells and text blocks are merged into
        visual lines; text elements inside a table region are skipped as duplicates.
        """
        regions = [region for table in self.tables if (region := _table_region(table))]
        blocks: list[tuple[int, Optional[BoundingBox], str]] = []
        for element in self.elements:
            if element.text.strip() and not _inside_any(element.bbox, regions):
                blocks.append((element.page_index, element.bbox, element.text.strip()))
        for table in self.tables:
            seen: set[int] = set()
            for cell in sorted(table.cells, key=lambda c: (c.row_index, c.col_index)):
                if id(cell) not in seen and cell.text.strip():
                    seen.add(id(cell))
                    page = cell.bbox.page_index if cell.bbox else table.page_index
                    blocks.append((page, cell.bbox, cell.text.strip()))
        return "\n".join(_visual_lines(blocks))


# A block joins a visual line when its vertical centre falls inside the line's band.
def _visual_lines(blocks: list[tuple[int, Optional[BoundingBox], str]]) -> list[str]:
    placed = sorted(
        ((page, bbox, text) for page, bbox, text in blocks if bbox is not None),
        key=lambda b: (b[0], (b[1].y0 + b[1].y1) / 2),
    )
    lines: list[tuple[int, float, float, list[tuple[float, str]]]] = []
    for page, bbox, text in placed:
        centre = (bbox.y0 + bbox.y1) / 2
        if lines and lines[-1][0] == page and lines[-1][1] <= centre <= lines[-1][2]:
            line_page, top, bottom, words = lines[-1]
            words.append((bbox.x0, text))
            lines[-1] = (line_page, min(top, bbox.y0), max(bottom, bbox.y1), words)
        else:
            lines.append((page, bbox.y0, bbox.y1, [(bbox.x0, text)]))
    rendered = [
        (page, " ".join(text for _, text in sorted(words, key=lambda w: w[0])))
        for page, _, _, words in lines
    ]
    unplaced = [(page, text) for page, bbox, text in blocks if bbox is None]
    ordered = sorted(rendered + unplaced, key=lambda item: item[0])
    return [text for _, text in ordered]


def _table_region(table: DocumentTable) -> Optional[BoundingBox]:
    if table.bbox is not None:
        return table.bbox
    boxes = [cell.bbox for cell in table.cells if cell.bbox is not None]
    if not boxes:
        return None
    return boxes[0].model_copy(
        update={
            "x0": min(b.x0 for b in boxes),
            "y0": min(b.y0 for b in boxes),
            "x1": max(b.x1 for b in boxes),
            "y1": max(b.y1 for b in boxes),
        }
    )


def _inside_any(bbox: Optional[BoundingBox], regions: list[BoundingBox]) -> bool:
    if bbox is None:
        return False
    cx, cy = (bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2
    return any(
        r.page_index == bbox.page_index and r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1
        for r in regions
    )
