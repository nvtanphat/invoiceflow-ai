from decimal import Decimal
import pytest
from benchmarks.scripts.evaluator import (
    evaluate_prediction,
    compute_field_exact_match,
    compute_line_items_f1,
)


def test_compute_field_exact_match():
    gt = {
        "supplier_tax_id": "0101234567",
        "invoice_number": "0001245",
        "currency": "VND",
        "subtotal": "50000000.0000",
        "tax_total": "5000000.0000",
        "amount_payable": "55000000.0000",
    }
    pred_exact = {
        "supplier_tax_id": "0101234567",
        "invoice_number": "0001245",
        "currency": "VND",
        "subtotal": "50000000.0000",
        "tax_total": "5000000.0000",
        "amount_payable": "55000000.0000",
    }
    score, mismatches = compute_field_exact_match(gt, pred_exact)
    assert score == 1.0
    assert len(mismatches) == 0

    pred_partial = {
        "supplier_tax_id": "0101234567",
        "invoice_number": "0009999",  # wrong
        "currency": "VND",
        "subtotal": "50000000.0000",
        "tax_total": "5000000.0000",
        "amount_payable": "55000000.0000",
    }
    score2, mismatches2 = compute_field_exact_match(gt, pred_partial)
    assert score2 == pytest.approx(5 / 6)
    assert "invoice_number" in mismatches2


def test_compute_line_items_f1():
    gt_lines = [
        {"sku": "DELL-XPS-13", "qty": "5.0000", "unit_price": "10000000.0000", "line_amount": "50000000.0000"},
        {"sku": "MOUSE-LOGI", "qty": "5.0000", "unit_price": "200000.0000", "line_amount": "1000000.0000"},
    ]
    pred_lines = [
        {"sku": "DELL-XPS-13", "qty": "5.0000", "unit_price": "10000000.0000", "line_amount": "50000000.0000"},
        {"sku": "MOUSE-LOGI", "qty": "5.0000", "unit_price": "200000.0000", "line_amount": "1000000.0000"},
    ]
    precision, recall, f1 = compute_line_items_f1(gt_lines, pred_lines)
    assert precision == 1.0
    assert recall == 1.0
    assert f1 == 1.0

    # One missing line in prediction
    pred_missing = [
        {"sku": "DELL-XPS-13", "qty": "5.0000", "unit_price": "10000000.0000", "line_amount": "50000000.0000"},
    ]
    p, r, f = compute_line_items_f1(gt_lines, pred_missing)
    assert p == 1.0
    assert r == 0.5
    assert f == pytest.approx(2 * (1.0 * 0.5) / (1.0 + 0.5))


def test_evaluate_prediction_overall():
    gt = {
        "header": {
            "supplier_tax_id": "0101234567",
            "invoice_number": "0001245",
            "amount_payable": "55000000.0000",
        },
        "lines": [
            {"sku": "DELL-XPS-13", "qty": "5.0000", "unit_price": "10000000.0000", "line_amount": "50000000.0000"},
        ],
        "expected_discrepancies": ["PRICE_MISMATCH"],
    }
    pred = {
        "header": {
            "supplier_tax_id": "0101234567",
            "invoice_number": "0001245",
            "amount_payable": "55000000.0000",
        },
        "lines": [
            {"sku": "DELL-XPS-13", "qty": "5.0000", "unit_price": "10000000.0000", "line_amount": "50000000.0000"},
        ],
        "detected_discrepancies": ["PRICE_MISMATCH"],
        "latency_ms": 120.5,
        "cost_usd": 0.0002,
    }
    result = evaluate_prediction(gt, pred)
    assert result["header_exact_match"] == 1.0
    assert result["lines_f1"] == 1.0
    assert result["anomaly_recall"] == 1.0
    assert result["latency_ms"] == 120.5
    assert result["cost_usd"] == 0.0002
