import pytest


def test_csv_formula_injection_escaping():
    from invoiceflow.infrastructure.storage.exporter import sanitize_csv_cell

    assert sanitize_csv_cell("Normal Supplier") == "Normal Supplier"
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert sanitize_csv_cell("-5+2") == "'-5+2"
