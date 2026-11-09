from decimal import Decimal
import re
from typing import Any, Dict, List, Optional
import unicodedata

from invoiceflow.domain.documents.models import DocumentCell, DocumentTable
from invoiceflow.domain.invoices.models import FieldEvidence, InvoiceLine

_BRACKET_SKU_PATTERN = re.compile(r"\[([A-Z0-9_-]+)(?:\]|\.[\d]*\s*|\s|$)")
_LINE_FIELD_PATH_PATTERN = re.compile(r"^lines\[(\d+)\]\.(.+)$")


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
        "sku": [
            "ma hang",
            "ma sp",
            "sku",
            "part no",
            "model",
            "ma so",
            "ma hang hoa",
            "ma vat tu",
            "ma dich vu",
            "item code",
        ],
        "description": [
            "ten hang hoa",
            "ten hang",
            "dich vu",
            "description",
            "noi dung",
            "hang hoa",
            "dien giai",
            "san pham",
            "ten hang hoa, dich vu",
            "ten vat tu",
            "ten vat tu, hang hoa",
            "quy cach",
            "noi dung hang hoa",
        ],
        "unit": ["don vi tinh", "dvt", "unit", "d.v.t", "don vi", "uom"],
        "qty": ["so luong", "sl", "qty", "quantity", "s.l", "so lg", "so luong thuc te"],
        "unit_price": [
            "don gia",
            "dg",
            "unit price",
            "price",
            "gia",
            "d.gia",
            "don gia sau thue",
            "don gia chua thue",
        ],
        "discount": ["chiet khau", "ck", "discount", "giam gia"],
        "tax_rate": [
            "thue suat",
            "vat %",
            "thue %",
            "tax rate",
            "% thue",
            "thue suat gtgt",
            "thue vat",
            "ts gtgt",
            "ts %",
        ],
        "line_amount": [
            "thanh tien",
            "amount",
            "total",
            "tien hang",
            "cong tien",
            "tien thanh toan",
            "thanh tien vnd",
        ],
    }

    _SUMMARY_ROW_PATTERNS = [
        "cong tien hang",
        "tong cong",
        "tien thue",
        "thue gtgt",
        "tong tien thanh toan",
        "chuyen sang trang sau",
        "mang sang tu trang truoc",
        "subtotal",
        "total amount",
    ]

    def extract_lines(self, tables: List[DocumentTable]) -> List[InvoiceLine]:
        lines, _ = self.extract_lines_with_evidence(tables)
        return lines

    def extract_invoice_lines(self, table: DocumentTable) -> List[InvoiceLine]:
        lines, _ = self.extract_invoice_lines_with_evidence(table)
        return lines

    def extract_lines_with_evidence(
        self, tables: List[DocumentTable]
    ) -> tuple[List[InvoiceLine], List[FieldEvidence]]:
        all_lines: List[InvoiceLine] = []
        all_evidence: List[FieldEvidence] = []
        for tab in tables:
            lines, evidence = self.extract_invoice_lines_with_evidence(tab)
            base_idx = len(all_lines)
            for ev in evidence:
                match = _LINE_FIELD_PATH_PATTERN.match(ev.field_path)
                if match:
                    local_idx, field = int(match.group(1)), match.group(2)
                    ev.field_path = f"lines[{base_idx + local_idx}].{field}"
                all_evidence.append(ev)
            all_lines.extend(lines)
        return all_lines, all_evidence

    def extract_invoice_lines_with_evidence(
        self, table: DocumentTable
    ) -> tuple[List[InvoiceLine], List[FieldEvidence]]:
        if not table.cells or table.row_count < 2:
            return [], []

        rows_map = self._build_rows_map(table.cells)
        sorted_row_indices = sorted(rows_map.keys())
        if not sorted_row_indices:
            return [], []

        col_mapping: Dict[int, str] = {}
        header_row_idx = sorted_row_indices[0]

        for r_idx in sorted_row_indices[:3]:
            row_cells = rows_map[r_idx]
            mapping = self._detect_column_headers(row_cells)
            if "description" in mapping.values() or "line_amount" in mapping.values():
                col_mapping = mapping
                header_row_idx = r_idx
                break

        if not col_mapping:
            col_mapping = self._fallback_column_mapping(table.column_count)

        lines: List[InvoiceLine] = []
        all_evidence: List[FieldEvidence] = []
        current_line: Optional[Dict[str, Any]] = None

        data_row_indices = [r for r in sorted_row_indices if r > header_row_idx]

        for r_idx in data_row_indices:
            row_cells = rows_map[r_idx]
            extracted_data = self._extract_row_data(row_cells, col_mapping, r_idx)

            if self._is_summary_row(extracted_data):
                if current_line is not None and self._has_line_identity(current_line):
                    line, evidence = self._finalize_line(current_line, len(lines) + 1, len(lines))
                    lines.append(line)
                    all_evidence.extend(evidence)
                    current_line = None
                continue

            if self._is_continuation_row(extracted_data, current_line):
                continuation_text = extracted_data.get("description", "").strip()
                if continuation_text and current_line:
                    current_line["description"] = (
                        f"{current_line['description']} {continuation_text}".strip()
                    )
                    cont_cell = extracted_data.get("_cells", {}).get("description")
                    cur_cell = current_line.get("_cells", {}).get("description")
                    if cur_cell and cur_cell.bbox and cont_cell and cont_cell.bbox:
                        cur_cell.bbox.x0 = min(cur_cell.bbox.x0, cont_cell.bbox.x0)
                        cur_cell.bbox.y0 = min(cur_cell.bbox.y0, cont_cell.bbox.y0)
                        cur_cell.bbox.x1 = max(cur_cell.bbox.x1, cont_cell.bbox.x1)
                        cur_cell.bbox.y1 = max(cur_cell.bbox.y1, cont_cell.bbox.y1)
                continue

            if current_line is not None and self._has_line_identity(current_line):
                line, evidence = self._finalize_line(current_line, len(lines) + 1, len(lines))
                lines.append(line)
                all_evidence.extend(evidence)
                current_line = None

            if self._has_line_identity(extracted_data):
                current_line = extracted_data

        if current_line is not None and self._has_line_identity(current_line):
            line, evidence = self._finalize_line(current_line, len(lines) + 1, len(lines))
            lines.append(line)
            all_evidence.extend(evidence)

        return lines, all_evidence

    def _build_rows_map(self, cells: List[DocumentCell]) -> Dict[int, Dict[int, DocumentCell]]:
        rows_map: Dict[int, Dict[int, DocumentCell]] = {}
        for cell in cells:
            for r in range(cell.row_index, cell.row_index + max(cell.rowspan, 1)):
                row_slots = rows_map.setdefault(r, {})
                for c in range(cell.col_index, cell.col_index + max(cell.colspan, 1)):
                    row_slots[c] = cell
        return rows_map

    def _has_line_identity(self, data: Dict[str, Any]) -> bool:
        return bool(
            data.get("description") or data.get("sku") or data.get("line_amount") is not None
        )

    def _detect_column_headers(self, cells: Dict[int, DocumentCell]) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        seen_cell_ids = set()
        for col_idx, cell in sorted(cells.items()):
            cell_key = id(cell)
            norm_text = _strip_accents(cell.text.strip())

            # Plain substring search (not word-bounded): table-structure
            # recognition frequently fuses adjacent header labels without a
            # separating space (e.g. "Thue suatThanh tien"), so a strict
            # \b...\b boundary would miss the second label entirely. False
            # positives from short acronym patterns are instead resolved by
            # preferring the longest, most specific match per cell below.
            matches: List[tuple[int, str, str]] = []
            for col_type, patterns in self.COLUMN_PATTERNS.items():
                for pattern in patterns:
                    pos = norm_text.find(pattern)
                    if pos >= 0:
                        matches.append((pos, col_type, pattern))

            if not matches:
                continue

            if cell.colspan > 1 and cell_key not in seen_cell_ids:
                # A merged header cell can bundle multiple column concepts
                # (e.g. "Thue suat" + "Thanh tien" fused by table-structure
                # recognition noise). Distribute distinct concepts, in the
                # order they appear in the text, across the spanned columns.
                seen_cell_ids.add(cell_key)
                ordered_fields: List[str] = []
                for _, col_type, _ in sorted(matches, key=lambda m: m[0]):
                    if col_type not in ordered_fields:
                        ordered_fields.append(col_type)
                span_cols = [c for c in range(col_idx, col_idx + cell.colspan)]
                for span_col, field in zip(span_cols, ordered_fields):
                    mapping[span_col] = field
            else:
                best = max(matches, key=lambda m: len(m[2]))
                mapping[col_idx] = best[1]

        return mapping

    def _fallback_column_mapping(self, column_count: int) -> Dict[int, str]:
        if column_count >= 6:
            return {
                0: "line_no",
                1: "description",
                2: "qty",
                3: "unit_price",
                4: "tax_rate",
                5: "line_amount",
            }
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
        self, cells: Dict[int, DocumentCell], mapping: Dict[int, str], row_idx: int
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        merged_fields: set[str] = set()
        for col_idx, field in mapping.items():
            cell = cells.get(col_idx)
            if not cell or not cell.text:
                continue

            # A colspan/rowspan expansion makes the same cell visible at
            # every column/row it covers. Only trust its text for the field
            # mapped to its true anchor position; a field mapped to one of
            # the "shadow" slots lost its real source cell to the merge and
            # must never be back-filled by blindly number-parsing a
            # neighbouring free-text cell (that fabricates values, e.g. a
            # stray digit in a product name reads as part of a quantity).
            is_anchor = cell.row_index == row_idx and cell.col_index == col_idx
            if not is_anchor:
                merged_fields.add(field)
                continue

            data[field] = cell.text.strip()
            data.setdefault("_cells", {})[field] = cell
            if cell.colspan > 1 or cell.rowspan > 1:
                merged_fields.add(field)

        if merged_fields:
            data["_merged_fields"] = merged_fields
        return data

    def _is_summary_row(self, data: Dict[str, Any]) -> bool:
        desc = _strip_accents(str(data.get("description", ""))).lower().strip()
        sku = _strip_accents(str(data.get("sku", ""))).lower().strip()
        row_text = f"{desc} {sku}".strip()
        return any(pattern in row_text for pattern in self._SUMMARY_ROW_PATTERNS)

    def _is_continuation_row(
        self, extracted: Dict[str, Any], current_line: Optional[Dict[str, Any]]
    ) -> bool:
        if current_line is None:
            return False
        line_no_str = str(extracted.get("line_no", "")).strip()
        has_valid_line_no = bool(line_no_str and re.search(r"\d", line_no_str))
        has_new_financials = has_valid_line_no or any(
            extracted.get(k) for k in ["sku", "qty", "unit_price", "line_amount"]
        )
        has_description = bool(extracted.get("description"))
        return not has_new_financials and has_description

    def _finalize_line(
        self, data: Dict[str, Any], fallback_line_no: int, local_idx: int
    ) -> tuple[InvoiceLine, List[FieldEvidence]]:
        source_cells: Dict[str, DocumentCell] = data.get("_cells", {})
        line_no_raw = data.get("line_no")
        try:
            line_no = int(re.sub(r"\D", "", line_no_raw)) if line_no_raw else fallback_line_no
        except Exception:
            line_no = fallback_line_no

        sku = data.get("sku")
        if sku:
            sku = sku.replace("\u00ad", "-").replace("–", "-").replace("—", "-").strip()
        desc = data.get("description", "Sản phẩm / Dịch vụ")
        unit = data.get("unit")

        sku_from_description = False
        if not sku:
            bracket_match = _BRACKET_SKU_PATTERN.search(desc)
            if bracket_match:
                sku = (
                    bracket_match.group(1)
                    .replace("\u00ad", "-")
                    .replace("–", "-")
                    .replace("—", "-")
                )
                desc = _BRACKET_SKU_PATTERN.sub("", desc).strip()
                sku_from_description = True
            else:
                m_unbr = re.search(r"\b([A-Z0-9]+(?:[-_/][A-Z0-9]+)+)\b", desc)
                if m_unbr:
                    cand = m_unbr.group(1)
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", cand) and not re.match(
                        r"^\d{10}-\d{3}$", cand
                    ):
                        sku = cand.replace("\u00ad", "-").replace("–", "-").replace("—", "-")
                        desc = desc.replace(cand, "").strip(" -:,")
                        sku_from_description = True

        raw_qty = data.get("qty", "")
        raw_price = data.get("unit_price", "0")
        raw_amount = data.get("line_amount", "0")

        if "%" in raw_amount:
            m_fused = re.search(r"([0-9.,]+)%\s*([0-9.,]+)", raw_amount)
            if m_fused:
                if not data.get("tax_rate"):
                    data["tax_rate"] = m_fused.group(1)
                raw_amount = m_fused.group(2)

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
        if qty == Decimal("0.0000") and qty_issue is None:
            issues.append("QTY_ZERO_OR_MISSING")
            if not raw_qty:
                issues.append("QTY_UNRECOVERED")

        merged_fields = data.get("_merged_fields")
        if merged_fields:
            issues.append("CELL_MERGE_SUSPECTED")

        expected = (qty * price) - discount
        if amount > Decimal("0.0000") and abs(amount - expected) >= Decimal("0.0100"):
            issues.append("ARITHMETIC_MISMATCH")

        line = InvoiceLine(
            line_no=line_no,
            sku_ref=sku,
            description=desc,
            unit=unit,
            raw_qty=raw_qty or None,
            qty=qty,
            raw_unit_price=raw_price,
            unit_price=price,
            discount=discount,
            tax_rate=tax_rate,
            raw_line_amount=raw_amount,
            line_amount=amount,
            issues=issues,
        )

        evidence = self._build_line_evidence(
            local_idx,
            source_cells,
            sku_from_description=sku_from_description,
            sku=sku,
            description=desc,
            qty=qty,
            unit_price=price,
            tax_rate=tax_rate,
            line_amount=amount,
        )
        return line, evidence

    def _build_line_evidence(
        self,
        local_idx: int,
        source_cells: Dict[str, DocumentCell],
        sku_from_description: bool,
        sku: Optional[str],
        description: str,
        qty: Decimal,
        unit_price: Decimal,
        tax_rate: Optional[Decimal],
        line_amount: Decimal,
    ) -> List[FieldEvidence]:
        field_values: Dict[str, tuple[Optional[str], str]] = {
            "sku_ref": (sku, "description" if sku_from_description else "sku"),
            "description": (description, "description"),
            "qty": (str(qty), "qty"),
            "unit_price": (str(unit_price), "unit_price"),
            "line_amount": (str(line_amount), "line_amount"),
        }
        if tax_rate is not None:
            field_values["tax_rate"] = (str(tax_rate), "tax_rate")

        evidence: List[FieldEvidence] = []
        for field, (value, source_key) in field_values.items():
            if value is None:
                continue
            cell = source_cells.get(source_key)
            if cell is None:
                continue
            evidence.append(
                FieldEvidence(
                    field_path=f"lines[{local_idx}].{field}",
                    source_kind="pdf_table",
                    page_index=cell.bbox.page_index if cell.bbox else None,
                    bbox=cell.bbox,
                    table_id=cell.table_id,
                    cell_id=cell.id,
                    raw_value=cell.text,
                    normalized_value=value,
                    confidence=1.0,
                    extractor="structure_aware_table_extractor",
                )
            )
        return evidence

    def _parse_decimal(self, val: Any, is_qty: bool = False) -> tuple[Decimal, Optional[str]]:
        if not val or not str(val).strip():
            return Decimal("0.0000"), None
        s = str(val).strip().replace("\u00a0", " ")
        # Strip currency symbols and clean outer whitespace
        s = re.sub(r"(?i)(?:vnd|vnđ|usd|eur|[₫đ$])", "", s).strip()
        # Normalise space-separated thousand groups e.g. "25 000 000"
        s = re.sub(r"(\d)\s+(\d{3})\b", r"\1\2", s)
        # A trailing "%" marks a percentage, never a thousands-grouped
        # integer; strip it before the separator heuristics below so e.g.
        # "10.00%" (a whole table cell value) isn't misread as "10,000%".
        if s.endswith("%"):
            s = s[:-1].strip()
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
