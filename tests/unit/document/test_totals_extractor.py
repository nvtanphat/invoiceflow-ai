from invoiceflow.infrastructure.document.totals_extractor import extract_invoice_totals


def _raw(text: str) -> dict[str, str]:
    return {field: match.raw for field, match in extract_invoice_totals(text).items()}


def test_reads_several_totals_on_one_ocr_line():
    """Regression: case_03/case_07 OCR keeps all totals on one line with short labels."""
    text = "Tien hang: 8500000.0000 Thue GTGT: 680000.0000 Tong cong: 9180000.0000"

    assert _raw(text) == {
        "subtotal": "8500000.0000",
        "tax_total": "680000.0000",
        "amount_payable": "9180000.0000",
    }


def test_reads_accented_multiline_labels_with_rate_and_currency():
    text = (
        "Cộng tiền hàng: 12.000.000 đ\n"
        "Thuế suất GTGT: 10%\n"
        "Tiền thuế GTGT (10%): 1.200.000 VND\n"
        "Tổng cộng tiền thanh toán: 13.200.000"
    )

    assert _raw(text) == {
        "subtotal": "12.000.000",
        "tax_total": "1.200.000",
        "amount_payable": "13.200.000",
    }


def test_uses_summary_occurrence_after_line_items():
    text = "Dong 1 Tien hang: 100.000\nDong 2 Tien hang: 200.000\nCong tien hang: 300.000"

    assert _raw(text)["subtotal"] == "300.000"


def test_percentages_are_not_tax_amounts_and_missing_totals_are_absent():
    totals = extract_invoice_totals("Thue GTGT: 10% \nTong cong: 1.100.000")

    assert "tax_total" not in totals
    assert "subtotal" not in totals
    assert totals["amount_payable"].raw == "1.100.000"


def test_decomposed_unicode_labels_are_matched():
    import unicodedata

    text = unicodedata.normalize("NFD", "Cộng tiền hàng: 5.000.000")

    assert _raw(text) == {"subtotal": "5.000.000"}


def test_ocr_garbled_amounts_are_not_truncated_into_small_numbers():
    """Regression (case_10): OCR read 0 as 'o'; '6ooo0000.0000' must not become 6."""
    text = (
        "Cong tien hang (Subtotal): 6ooo0000.0000\n"
        "Tien thue GTGT (Tax Total): 6000000.0000\n"
        "Tong cong (Total Amount): 66oo0000.0000"
    )

    assert _raw(text) == {"tax_total": "6000000.0000"}


def test_plain_total_label_and_currency_symbol_are_read():
    assert _raw("SubTotal: 63,636\nTotal: 59,500") == {
        "subtotal": "63,636",
        "amount_payable": "59,500",
    }
    assert _raw("Total $ 216,67") == {"amount_payable": "216,67"}


def test_label_followed_by_several_amounts_is_not_assigned_to_one_field():
    """A summary row such as 'Total 196,97 19,70 216,67' does not say which amount is
    payable; taking the first one would record the pre-tax subtotal as amount payable."""
    assert _raw("Total $ 196,97 $ 19,70 $ 216,67") == {}
    assert _raw("Tong cong: 7.000.000 560.000 7.560.000") == {}


def test_total_label_without_an_adjacent_amount_is_ignored():
    assert _raw("Total Qty 2\nTotal Items: 3 pcs") == {}
