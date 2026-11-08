from decimal import Decimal
from typing import Any, Optional

_AMOUNT_TOLERANCE = Decimal("1.0")
_STRUCTURAL_FIELDS = ["qty", "unit_price", "line_amount"]


def average_arithmetic_validity(case_scores: list[dict[str, Any]]) -> Optional[float]:
    """Averages arithmetic_validity_rate across cases, skipping cases where
    it is None (no checkable qty/price/amount data at all) rather than
    treating "nothing to check" as a fabricated 100% pass.
    """
    applicable = [
        s["arithmetic_validity_rate"]
        for s in case_scores
        if s.get("arithmetic_validity_rate") is not None
    ]
    if not applicable:
        return None
    return sum(applicable) / len(applicable)


def normalize_discrepancy(code: str) -> str:
    c = str(code).upper().strip()
    if "PRICE" in c:
        return "PRICE_MISMATCH"
    if "QUANTITY" in c or "QTY" in c:
        return "QUANTITY_MISMATCH"
    return c


def compute_field_exact_match(gt: dict[str, Any], pred: dict[str, Any]) -> tuple[float, list[str]]:
    if not gt:
        return 1.0, []
    matches = 0
    mismatches: list[str] = []
    for k, v_gt in gt.items():
        v_pred = pred.get(k)
        if v_gt is None and v_pred is None:
            matches += 1
            continue
        if v_gt is None or v_pred is None:
            mismatches.append(k)
            continue

        s_gt = str(v_gt).strip()
        s_pred = str(v_pred).strip()

        # Decimal numerical equality check
        try:
            d_gt = Decimal(s_gt)
            d_pred = Decimal(s_pred)
            if d_gt == d_pred:
                matches += 1
                continue
        except Exception:
            pass

        if s_gt.lower() == s_pred.lower():
            matches += 1
        else:
            mismatches.append(k)

    score = matches / len(gt) if len(gt) > 0 else 1.0
    return score, mismatches


def _sku_identity_match(gt_sku: str, pred_sku: str) -> bool:
    if not gt_sku or not pred_sku:
        return False
    if gt_sku == pred_sku:
        return True
    # Containment is only trusted above a length floor; short codes (e.g.
    # "A4") would otherwise match almost any longer SKU that happens to
    # contain the same substring.
    return len(gt_sku) >= 4 and (gt_sku in pred_sku or pred_sku in gt_sku)


def _amount_match(gt_amount: Any, pred_amount: Any) -> bool:
    if gt_amount is None or pred_amount is None:
        return False
    try:
        return abs(Decimal(str(gt_amount)) - Decimal(str(pred_amount))) <= _AMOUNT_TOLERANCE
    except Exception:
        return str(gt_amount) == str(pred_amount)


def _line_identity_and_amount_match(gt_item: dict[str, Any], pred_item: dict[str, Any]) -> bool:
    # A line only counts as extracted correctly when BOTH a stable identity
    # signal (sku, falling back to description containment when no sku is
    # present) AND the line amount agree. Either signal alone is far too
    # easy to satisfy by chance across invoice lines with repeated amounts
    # or near-duplicate product names.
    gt_sku = (gt_item.get("sku") or "").strip().lower()
    pred_sku = (pred_item.get("sku") or "").strip().lower()
    gt_desc = (gt_item.get("description") or "").strip().lower()
    pred_desc = (pred_item.get("description") or "").strip().lower()

    if gt_sku or pred_sku:
        identity_match = _sku_identity_match(gt_sku, pred_sku)
    else:
        identity_match = bool(gt_desc) and bool(pred_desc) and (
            gt_desc in pred_desc or pred_desc in gt_desc
        )

    return identity_match and _amount_match(gt_item.get("line_amount"), pred_item.get("line_amount"))


def compute_line_items_f1(
    gt_lines: list[dict[str, Any]], pred_lines: list[dict[str, Any]]
) -> tuple[float, float, float]:
    if not gt_lines and not pred_lines:
        return 1.0, 1.0, 1.0
    if not gt_lines and pred_lines:
        return 0.0, 1.0, 0.0
    if gt_lines and not pred_lines:
        return 1.0, 0.0, 0.0

    unmatched_gt = list(range(len(gt_lines)))
    unmatched_pred = list(range(len(pred_lines)))
    matches = 0

    for i in list(unmatched_gt):
        gt_item = gt_lines[i]
        for j in list(unmatched_pred):
            pred_item = pred_lines[j]
            if _line_identity_and_amount_match(gt_item, pred_item):
                matches += 1
                unmatched_gt.remove(i)
                unmatched_pred.remove(j)
                break

    precision = matches / len(pred_lines) if len(pred_lines) > 0 else 0.0
    recall = matches / len(gt_lines) if len(gt_lines) > 0 else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * (precision * recall) / (precision + recall)
    return precision, recall, f1


def _is_structurally_complete(line: dict[str, Any]) -> bool:
    return all(line.get(field) not in (None, "") for field in _STRUCTURAL_FIELDS)


def compute_table_structure_f1(
    gt_lines: list[dict[str, Any]], pred_lines: list[dict[str, Any]]
) -> tuple[float, float, float]:
    """Measures whether rows were extracted with every numeric structural
    slot populated (qty/unit_price/line_amount), by row position.

    This is deliberately independent of whether the VALUES inside those
    slots are semantically correct (that is Line Item F1's job) and of
    whether the arithmetic holds (Arithmetic Validity's job) -- it isolates
    the table extractor's structural recognition quality: did it find the
    right number of rows with the right columns populated, e.g. not losing
    a quantity to a merged cell.
    """
    if not gt_lines and not pred_lines:
        return 1.0, 1.0, 1.0
    if not gt_lines and pred_lines:
        return 0.0, 1.0, 0.0
    if gt_lines and not pred_lines:
        return 1.0, 0.0, 0.0

    aligned_count = min(len(gt_lines), len(pred_lines))
    complete_count = sum(
        1 for i in range(aligned_count) if _is_structurally_complete(pred_lines[i])
    )

    precision = complete_count / len(pred_lines)
    recall = complete_count / len(gt_lines)
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * (precision * recall) / (precision + recall)
    return precision, recall, f1


def compute_table_extraction_quality(
    gt_lines: list[dict[str, Any]], pred_lines: list[dict[str, Any]]
) -> dict[str, Optional[float]]:
    p, r, f1 = compute_table_structure_f1(gt_lines, pred_lines)

    valid_arithmetic = 0
    total_checked = 0
    for item in pred_lines:
        try:
            qty_str = item.get("qty")
            price_str = item.get("unit_price")
            amt_str = item.get("line_amount")
            if qty_str is not None and price_str is not None and amt_str is not None:
                qty = Decimal(str(qty_str))
                price = Decimal(str(price_str))
                amt = Decimal(str(amt_str))
                total_checked += 1
                if abs((qty * price) - amt) <= Decimal("1.0"):
                    valid_arithmetic += 1
        except Exception:
            pass

    # No case with enough data to check arithmetic on is "not applicable",
    # never a fabricated perfect score.
    arithmetic_validity: Optional[float] = (
        (valid_arithmetic / total_checked) if total_checked > 0 else None
    )

    return {
        "table_precision": p,
        "table_recall": r,
        "table_f1": f1,
        "arithmetic_validity_rate": arithmetic_validity,
    }


def evaluate_prediction(gt: dict[str, Any], pred: dict[str, Any]) -> dict[str, Any]:
    header_score, header_mismatches = compute_field_exact_match(
        gt.get("header", {}), pred.get("header", {})
    )
    lines_p, lines_r, lines_f1 = compute_line_items_f1(gt.get("lines", []), pred.get("lines", []))
    table_quality = compute_table_extraction_quality(gt.get("lines", []), pred.get("lines", []))

    expected_anomalies = {normalize_discrepancy(x) for x in gt.get("expected_discrepancies", [])}
    detected_anomalies = {normalize_discrepancy(x) for x in pred.get("detected_discrepancies", [])}

    if not expected_anomalies and not detected_anomalies:
        anomaly_p, anomaly_r, anomaly_f1 = 1.0, 1.0, 1.0
    elif not expected_anomalies and detected_anomalies:
        anomaly_p, anomaly_r, anomaly_f1 = 0.0, 1.0, 0.0
    elif expected_anomalies and not detected_anomalies:
        anomaly_p, anomaly_r, anomaly_f1 = 1.0, 0.0, 0.0
    else:
        intersection = len(expected_anomalies & detected_anomalies)
        anomaly_p = intersection / len(detected_anomalies)
        anomaly_r = intersection / len(expected_anomalies)
        anomaly_f1 = (
            2 * (anomaly_p * anomaly_r) / (anomaly_p + anomaly_r)
            if (anomaly_p + anomaly_r) > 0
            else 0.0
        )

    doc_em = 1.0 if (len(header_mismatches) == 0 and len(gt.get("header", {})) > 0) else 0.0

    return {
        "header_exact_match": header_score,
        "header_document_exact_match": doc_em,
        "header_mismatches": header_mismatches,
        "lines_precision": lines_p,
        "lines_recall": lines_r,
        "lines_f1": lines_f1,
        "table_f1": table_quality["table_f1"],
        "table_precision": table_quality["table_precision"],
        "table_recall": table_quality["table_recall"],
        "arithmetic_validity_rate": table_quality["arithmetic_validity_rate"],
        "anomaly_precision": anomaly_p,
        "anomaly_recall": anomaly_r,
        "anomaly_f1": anomaly_f1,
        "latency_ms": pred.get("latency_ms", 0.0),
        "cost_usd": pred.get("cost_usd", 0.0),
    }
