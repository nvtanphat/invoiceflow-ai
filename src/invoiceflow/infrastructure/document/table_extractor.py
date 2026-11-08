from decimal import Decimal
import re
from typing import Any, Dict, List, Optional
import unicodedata

from invoiceflow.domain.documents.models import DocumentCell, DocumentTable
from invoiceflow.domain.invoices.models import InvoiceLine


def _strip_accents(text: str) -> str:
    cleaned = text.replace("đ", "d").replace("Đ", "d")
    nfkd = unicodedata.normalize("NFKD", cleaned)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


class StructureAwareTableExtractor:
    """Structure-aware extractor converting DocumentTable grids into verified InvoiceLine models.

    Identifies standard Vietnamese and international invoice column semantics,
    merges multi-line wrapped descriptions, preserves cell provenance, and
    performs deterministic arithmetic checks without mutating financial truth.
    """

    COLUMN_PATTERNS: Dict[str, List[str]] = {
        "line_no": ["stt", "no", "item", "tt"],
        "sku": ["ma hang", "ma sp", "code", "sku", "part no", "model"],
        "description": [
            "ten hang hoa",
            "ten hang",
            "dich vu",
            "description",
            "noi dung",
            "hang hoa",
            "dien giai",
            "san pham",
        ],
        "unit": ["don vi tinh", "dvt", "unit"],
        "qty": ["so luong", "sl", "qty", "quantity"],
        "unit_price": ["don gia", "dg", "unit price", "price", "gia"],
        "discount": ["chiet khau", "ck", "discount", "giam gia"],
        "tax_rate": ["thue suat", "vat %", "thue %", "tax rate", "% thue"],
        "line_amount": ["thanh tien", "amount", "total", "tien hang"],
    }

    def extract_lines(self, tables: List[DocumentTable]) -> List[InvoiceLine]:
        all_lines: List[InvoiceLine] = []
        for tab in tables:
            lines = self.extract_invoice_lines(tab)
            all_lines.extend(lines)
        return all_lines

    def extract_invoice_lines(self, table: DocumentTable) -> List[InvoiceLine]:
        if not table.cells or table.row_count < 2:
            return []

        # 1. Group cells by row
        rows_map: Dict[int, Dict[int, DocumentCell]] = {}
        for c in table.cells:
            if c.row_index not in rows_map:
                rows_map[c.row_index] = {}
            rows_map[c.row_index][c.col_index] = c

        sorted_row_indices = sorted(rows_map.keys())
        if not sorted_row_indices:
            return []

        # 2. Identify header row and column semantics
        col_mapping: Dict[int, str] = {}
        header_row_idx = sorted_row_indices[0]

        # Scan initial rows (up to 3) to find the best header match
        for r_idx in sorted_row_indices[:3]:
            row_cells = rows_map[r_idx]
            mapping = self._detect_column_headers(row_cells)
            # A valid header must at least recognize description or line_amount or qty
            if "description" in mapping.values() or "line_amount" in mapping.values():
                col_mapping = mapping
                header_row_idx = r_idx
                break

        if not col_mapping:
            # Fallback heuristic: assume left-to-right standard order
            col_mapping = self._fallback_column_mapping(table.column_count)

        # 3. Process data rows & handle multi-line wrapped descriptions
        lines: List[InvoiceLine] = []
        current_line: Optional[Dict[str, Any]] = None

        data_row_indices = [r for r in sorted_row_indices if r > header_row_idx]

        for r_idx in data_row_indices:
            row_cells = rows_map[r_idx]
            extracted_data = self._extract_row_data(row_cells, col_mapping)

            # Check if this row is a continuation of the previous row (e.g. wrapped description)
            if self._is_continuation_row(extracted_data, current_line):
                continuation_text = extracted_data.get("description", "").strip()
                if continuation_text and current_line:
                    current_line["description"] = (
                        f"{current_line['description']} {continuation_text}".strip()
                    )
                continue

            # If we had a previously accumulated line, finalize it
            if current_line is not None and current_line.get("description"):
                lines.append(self._finalize_line(current_line, len(lines) + 1))
                current_line = None

            # Start a new line if there is meaningful data
            if extracted_data.get("description") or extracted_data.get("line_amount") is not None:
                current_line = extracted_data

        # Finalize the last line
        if current_line is not None and current_line.get("description"):
            lines.append(self._finalize_line(current_line, len(lines) + 1))

        return lines

    def _detect_column_headers(self, cells: Dict[int, DocumentCell]) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        for col_idx, cell in cells.items():
            norm_text = _strip_accents(cell.text.strip())
            for col_type, patterns in self.COLUMN_PATTERNS.items():
                if any(p in norm_text for p in patterns):
                    mapping[col_idx] = col_type
                    break
        return mapping

    def _fallback_column_mapping(self, column_count: int) -> Dict[int, str]:
        # Minimal default mapping
        if column_count >= 5:
            return {
                0: "line_no",
                1: "description",
                2: "qty",
                3: "unit_price",
                4: "line_amount",
            }
        return {0: "description", 1: "line_amount"}

    def _extract_row_data(
        self, cells: Dict[int, DocumentCell], mapping: Dict[int, str]
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for col_idx, field in mapping.items():
            cell = cells.get(col_idx)
            if cell and cell.text:
                data[field] = cell.text.strip()
                # Track primary bounding box from line_amount or description
                if field in ("line_amount", "description") and cell.bbox:
                    data.setdefault("bbox", cell.bbox)
        return data

    def _is_continuation_row(
        self, extracted: Dict[str, Any], current_line: Optional[Dict[str, Any]]
    ) -> bool:
        if current_line is None:
            return False
        # If line has no new line_no, no quantity, and no line_amount, but has description
        has_new_financials = any(
            extracted.get(k) for k in ["line_no", "qty", "unit_price", "line_amount"]
        )
        has_description = bool(extracted.get("description"))
        return not has_new_financials and has_description

    def _finalize_line(self, data: Dict[str, Any], fallback_line_no: int) -> InvoiceLine:
        line_no_raw = data.get("line_no")
        try:
            line_no = int(re.sub(r"\D", "", line_no_raw)) if line_no_raw else fallback_line_no
        except Exception:
            line_no = fallback_line_no

        sku = data.get("sku")
        desc = data.get("description", "Sản phẩm / Dịch vụ")
        unit = data.get("unit")

        raw_qty = data.get("qty", "1")
        raw_price = data.get("unit_price", "0")
        raw_amount = data.get("line_amount", "0")

        qty, qty_issue = self._parse_decimal(raw_qty, is_qty=True)
        price, price_issue = self._parse_decimal(raw_price)
        amount, amount_issue = self._parse_decimal(raw_amount)

        discount = Decimal("0.0000")
        if data.get("discount"):
            discount, _ = self._parse_decimal(data["discount"])

        tax_rate: Optional[Decimal] = None
        if data.get("tax_rate"):
            tr, _ = self._parse_decimal(data["tax_rate"])
            tax_rate = tr

        issues: List[str] = []
        if qty_issue:
            issues.append(qty_issue)
        if price_issue:
            issues.append(price_issue)
        if amount_issue:
            issues.append(amount_issue)

        # Intrinsic arithmetic verification
        expected = (qty * price) - discount
        # If amount was explicitly parsed and does not match expected
        if amount > Decimal("0.0000") and abs(amount - expected) >= Decimal("0.0100"):
            issues.append("ARITHMETIC_MISMATCH")

        return InvoiceLine(
            line_no=line_no,
            sku_ref=sku,
            description=desc,
            unit=unit,
            raw_qty=raw_qty,
            qty=qty if qty > 0 else Decimal("1.0000"),
            raw_unit_price=raw_price,
            unit_price=price,
            discount=discount,
            tax_rate=tax_rate,
            raw_line_amount=raw_amount,
            line_amount=amount,
            issues=issues,
        )

    def _parse_decimal(self, val: Any, is_qty: bool = False) -> tuple[Decimal, Optional[str]]:
        if not val or not str(val).strip():
            return Decimal("0.0000"), None
        s = str(val).strip()
        issue: Optional[str] = None

        if not re.search(r"\d", s):
            return Decimal("0.0000"), "PARSE_ERROR"

        # Multi-separator disambiguation
        if "." in s and "," in s:
            if s.rfind(",") > s.rfind("."):
                # 12.000.000,00 -> standard VN decimal
                s = s.replace(".", "").replace(",", ".")
            else:
                # 12,000,000.00 -> US decimal
                s = s.replace(",", "")
        elif "." in s:
            parts = s.split(".")
            if is_qty and len(parts) == 2:
                s = f"{parts[0]}.{parts[1]}"
            elif len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                # 12.000.000 -> Vietnamese thousand dots
                s = s.replace(".", "")
            elif len(parts) == 2 and len(parts[1]) != 3:
                pass  # standard dot decimal
            else:
                issue = "AMBIGUOUS_NUMBER"
        elif "," in s:
            parts = s.split(",")
            if is_qty and len(parts) == 2 and len(parts[1]) == 3:
                issue = "AMBIGUOUS_NUMBER"
                s = s.replace(",", "")
            elif len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                s = s.replace(",", "")
            elif len(parts) == 2 and len(parts[1]) != 3:
                s = s.replace(",", ".")
            else:
                issue = "AMBIGUOUS_NUMBER"
                s = s.replace(",", "")

        clean = re.sub(r"[^\d.-]", "", s)
        try:
            return Decimal(clean), issue
        except Exception:
            return Decimal("0.0000"), "PARSE_ERROR"
