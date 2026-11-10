from invoiceflow.domain.documents.value_parsing import parse_vn_decimal
from decimal import Decimal


def test_numeric_parsing_distinguishes_vietnamese_and_us_formats():

    # 1. Standard Vietnamese thousand dots: 12.000.000
    val, issue = parse_vn_decimal("12.000.000")
    assert val == Decimal("12000000")
    assert issue is None

    # 2. Standard US thousand commas: 12,000,000
    val, issue = parse_vn_decimal("12,000,000")
    assert val == Decimal("12000000")
    assert issue is None

    # 3. Vietnamese comma decimal with dot thousand: 1.234,56
    val, issue = parse_vn_decimal("1.234,56")
    assert val == Decimal("1234.56")
    assert issue is None

    # 4. US dot decimal with comma thousand: 1,234.56
    val, issue = parse_vn_decimal("1,234.56")
    assert val == Decimal("1234.56")
    assert issue is None

    # 5. Simple decimal: 5.5
    val, issue = parse_vn_decimal("5.5", is_qty=True)
    assert val == Decimal("5.5")
    assert issue is None

    # 6. Currency with three trailing zeros: 200.000
    val, issue = parse_vn_decimal("200.000")
    assert val == Decimal("200000")
    assert issue is None

    # 7. Ambiguous quantity: 5,500 in quantity column
    val, issue = parse_vn_decimal("5,500", is_qty=True)
    # Must flag ambiguity when unsure whether it's 5.5 or 5500
    assert issue == "AMBIGUOUS_NUMBER"

    # 8. Complete invalid text
    val, issue = parse_vn_decimal("N/A")
    assert val == Decimal("0.0000")
    assert issue == "PARSE_ERROR"


def test_printed_dates_and_tax_ids_normalise_across_formats():
    from datetime import date

    from invoiceflow.domain.documents.value_parsing import normalize_tax_id, parse_printed_date

    assert parse_printed_date("2026-03-20") == date(2026, 3, 20)
    assert parse_printed_date("2026\u00ad03\u00ad01") == date(2026, 3, 1)
    assert parse_printed_date("20/03/2026") == date(2026, 3, 20)
    assert parse_printed_date("Ngày 20 tháng 03 năm 2026") == date(2026, 3, 20)
    assert parse_printed_date("32/13/2026") is None
    assert normalize_tax_id("0101 234 567") == "0101234567"
    assert normalize_tax_id("0101234567 - 001") == "0101234567-001"
    assert normalize_tax_id("0101234567\u00ad001") == "0101234567-001"
