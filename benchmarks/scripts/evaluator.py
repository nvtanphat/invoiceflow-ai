from typing import Any


def compute_field_exact_match(
    gt: dict[str, Any], pred: dict[str, Any]
) -> tuple[float, list[str]]:
    if not gt:
        return 1.0, []
    matches = 0
    mismatches: list[str] = []
    for k, v_gt in gt.items():
        v_pred = pred.get(k)
        # Normalize comparison: strings stripped, decimals converted to float/string
        s_gt = str(v_gt).strip() if v_gt is not None else ""
        s_pred = str(v_pred).strip() if v_pred is not None else ""
        if s_gt == s_pred:
            matches += 1
        else:
            mismatches.append(k)
    score = matches / len(gt) if len(gt) > 0 else 1.0
    return score, mismatches


def compute_line_items_f1(
    gt_lines: list[dict[str, Any]], pred_lines: list[dict[str, Any]]
) -> tuple[float, float, float]:
    if not gt_lines and not pred_lines:
        return 1.0, 1.0, 1.0
    if not gt_lines and pred_lines:
        return 0.0, 1.0, 0.0
    if gt_lines and not pred_lines:
        return 1.0, 0.0, 0.0

    # Match lines based on sku/description and line_amount
    unmatched_gt = list(range(len(gt_lines)))
    unmatched_pred = list(range(len(pred_lines)))
    matches = 0

    for i in list(unmatched_gt):
        gt_item = gt_lines[i]
        gt_key = (
            (gt_item.get("sku") or "").strip().lower(),
            str(gt_item.get("line_amount") or "").strip(),
        )
        for j in list(unmatched_pred):
            pred_item = pred_lines[j]
            pred_key = (
                (pred_item.get("sku") or "").strip().lower(),
                str(pred_item.get("line_amount") or "").strip(),
            )
            if gt_key == pred_key:
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


def evaluate_prediction(
    gt: dict[str, Any], pred: dict[str, Any]
) -> dict[str, Any]:
    header_score, header_mismatches = compute_field_exact_match(
        gt.get("header", {}), pred.get("header", {})
    )
    lines_p, lines_r, lines_f1 = compute_line_items_f1(
        gt.get("lines", []), pred.get("lines", [])
    )

    # Anomaly evaluation
    expected_anomalies = set(gt.get("expected_discrepancies", []))
    detected_anomalies = set(pred.get("detected_discrepancies", []))
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

    return {
        "header_exact_match": header_score,
        "header_mismatches": header_mismatches,
        "lines_precision": lines_p,
        "lines_recall": lines_r,
        "lines_f1": lines_f1,
        "anomaly_precision": anomaly_p,
        "anomaly_recall": anomaly_r,
        "anomaly_f1": anomaly_f1,
        "latency_ms": pred.get("latency_ms", 0.0),
        "cost_usd": pred.get("cost_usd", 0.0),
    }
