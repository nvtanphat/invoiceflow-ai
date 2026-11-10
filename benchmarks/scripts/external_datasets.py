"""Ground-truth adapters for independent public datasets (data stays outside the repo).

Each adapter maps a dataset's own annotation schema onto the benchmark schema used by
``benchmarks/scripts/evaluator.py``. Number and date conventions are properties of the
*annotations* of each dataset (CORD: Indonesian rupiah, '.'/',' as thousands separators;
Sparrow: comma decimals, US dates), so they are decoded here, never in the pipeline.

Sources and licences (checked 2026-11-10):
- CORD v2 (naver-clova-ix/cord-v2, CC BY 4.0): real photographed Indonesian receipts.
- Sparrow invoices (katanaml-org/invoices-donut-data-v1, MIT): generated e-invoice images
  (Kozłowski & Weichbroth 2021, Mendeley "Samples of electronic invoices") -> synthetic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any, Iterator, Optional

# Deterministic dev/holdout assignment: error analysis uses only the dataset's own
# validation split; the test split is the untouched holdout.
SPLITS = {"dev": "validation", "holdout": "test"}


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    folder: str
    document_kind: str  # "receipt" | "invoice"
    provenance: str  # "real" | "synthetic"
    licence: str


CORD = DatasetSpec("cord_v2", "cord_v2", "receipt", "real", "CC BY 4.0")
SPARROW = DatasetSpec("sparrow", "sparrow", "invoice", "synthetic", "MIT")
DATASETS = {spec.name: spec for spec in (CORD, SPARROW)}


@dataclass
class ExternalCase:
    case_id: str
    dataset: DatasetSpec
    image_bytes: bytes
    filename: str
    header: dict[str, Optional[str]]
    lines: list[dict[str, Optional[str]]]
    reference_text: Optional[str] = None
    field_boxes: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)


def parse_cord_amount(raw: Any) -> Optional[str]:
    """CORD amounts are whole rupiah; '.' and ',' only group thousands ('60.000', '1,500')."""
    if raw is None:
        return None
    text = str(raw).strip()
    negative = text.startswith("-") or text.startswith("(")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    return str(-int(digits) if negative else int(digits))


def parse_comma_decimal(raw: Any) -> Optional[str]:
    """Sparrow amounts use a decimal comma and optional space/dot grouping ('$ 1 234,50')."""
    if raw is None:
        return None
    text = re.sub(r"[^\d,.\-]", "", str(raw))
    if not re.search(r"\d", text):
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return str(Decimal(text).normalize())
    except InvalidOperation:
        return None


def parse_us_date(raw: Any) -> Optional[str]:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def cord_ground_truth(gt: dict[str, Any]) -> tuple[dict[str, Optional[str]], list[dict]]:
    parse = gt["gt_parse"]
    sub_total = parse.get("sub_total") or {}
    total = parse.get("total") or {}
    header = {
        "subtotal": parse_cord_amount(sub_total.get("subtotal_price")),
        "tax_total": parse_cord_amount(sub_total.get("tax_price")),
        "amount_payable": parse_cord_amount(total.get("total_price")),
    }
    lines = [
        {
            "sku": "",
            "description": str(item.get("nm") or "").strip(),
            "qty": parse_cord_amount(item.get("cnt")),
            "unit_price": parse_cord_amount(item.get("unitprice")),
            # CORD "price" is the line total.
            "line_amount": parse_cord_amount(item.get("price")),
        }
        for item in _as_list(parse.get("menu"))
        if item.get("nm")
    ]
    return header, lines


def cord_reference_text(gt: dict[str, Any]) -> str:
    """Full receipt text from annotated words: rows top-to-bottom, words left-to-right."""
    rows: dict[int, list[tuple[float, float, str]]] = {}
    for line in gt.get("valid_line", []):
        for word in line.get("words", []):
            quad = word["quad"]
            y = (quad["y1"] + quad["y3"]) / 2
            rows.setdefault(word["row_id"], []).append((y, quad["x1"], word["text"]))
    ordered = sorted(rows.values(), key=lambda words: sum(w[0] for w in words) / len(words))
    return "\n".join(" ".join(w[2] for w in sorted(words, key=lambda w: w[1])) for words in ordered)


def cord_field_boxes(gt: dict[str, Any]) -> dict[str, tuple[float, float, float, float]]:
    """Pixel box of the annotated total amount, used for bbox accuracy of amount_payable."""
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for line in gt.get("valid_line", []):
        if line.get("category") != "total.total_price":
            continue
        xs = [w["quad"][k] for w in line["words"] for k in ("x1", "x2", "x3", "x4")]
        ys = [w["quad"][k] for w in line["words"] for k in ("y1", "y2", "y3", "y4")]
        if xs and ys:
            boxes["amount_payable"] = (min(xs), min(ys), max(xs), max(ys))
            break
    return boxes


def sparrow_ground_truth(gt: dict[str, Any]) -> tuple[dict[str, Optional[str]], list[dict]]:
    parse = gt["gt_parse"]
    # Some records are flat (no header/items/summary wrappers).
    flat = "header" not in parse and "invoice_no" in parse
    head = parse if flat else parse.get("header") or {}
    summary = parse if flat else parse.get("summary") or {}
    items = [parse] if flat else _as_list(parse.get("items"))
    header = {
        "invoice_number": (str(head["invoice_no"]).strip() if head.get("invoice_no") else None),
        "issue_date": parse_us_date(head.get("invoice_date")),
        "subtotal": parse_comma_decimal(summary.get("total_net_worth")),
        "tax_total": parse_comma_decimal(summary.get("total_vat")),
        "amount_payable": parse_comma_decimal(summary.get("total_gross_worth")),
    }
    lines = [
        {
            "sku": "",
            "description": str(item.get("item_desc") or "").strip(),
            "qty": parse_comma_decimal(item.get("item_qty")),
            "unit_price": parse_comma_decimal(item.get("item_net_price")),
            # Net (pre-tax) line worth, the same basis as the pipeline's line_amount.
            "line_amount": parse_comma_decimal(item.get("item_net_worth")),
        }
        for item in items
        if item.get("item_desc")
    ]
    return header, lines


def load_cases(
    data_dir: Path, dataset: str, split: str, limit: Optional[int] = None
) -> Iterator[ExternalCase]:
    import pandas as pd

    spec = DATASETS[dataset]
    frame = pd.read_parquet(data_dir / spec.folder / f"{SPLITS[split]}.parquet")
    if limit is not None:
        frame = frame.head(limit)
    for index, row in frame.iterrows():
        gt = json.loads(row["ground_truth"])
        if spec is CORD:
            header, lines = cord_ground_truth(gt)
            reference, boxes = cord_reference_text(gt), cord_field_boxes(gt)
        else:
            header, lines = sparrow_ground_truth(gt)
            reference, boxes = None, {}
        yield ExternalCase(
            case_id=f"{spec.name}-{SPLITS[split]}-{index:03d}",
            dataset=spec,
            image_bytes=row["image"]["bytes"],
            filename=f"{spec.name}_{index:03d}.jpg",
            header=header,
            lines=lines,
            reference_text=reference,
            field_boxes=boxes,
        )
