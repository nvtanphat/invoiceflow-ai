from decimal import Decimal
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser


def test_numeric_parsing_distinguishes_vietnamese_and_us_formats():
    parser = DigitalPDFParser()

    # 1. Standard Vietnamese thousand dots: 12.000.000
    val, issue = parser._parse_decimal("12.000.000")
    assert val == Decimal("12000000")
    assert issue is None

    # 2. Standard US thousand commas: 12,000,000
    val, issue = parser._parse_decimal("12,000,000")
    assert val == Decimal("12000000")
    assert issue is None

    # 3. Vietnamese comma decimal with dot thousand: 1.234,56
    val, issue = parser._parse_decimal("1.234,56")
    assert val == Decimal("1234.56")
    assert issue is None

    # 4. US dot decimal with comma thousand: 1,234.56
    val, issue = parser._parse_decimal("1,234.56")
    assert val == Decimal("1234.56")
    assert issue is None

    # 5. Simple decimal: 5.5
    val, issue = parser._parse_decimal("5.5", is_qty=True)
    assert val == Decimal("5.5")
    assert issue is None

    # 6. Currency with three trailing zeros: 200.000
    val, issue = parser._parse_decimal("200.000")
    assert val == Decimal("200000")
    assert issue is None

    # 7. Ambiguous quantity: 5,500 in quantity column
    val, issue = parser._parse_decimal("5,500", is_qty=True)
    # Must flag ambiguity when unsure whether it's 5.5 or 5500
    assert issue == "AMBIGUOUS_NUMBER"

    # 8. Complete invalid text
    val, issue = parser._parse_decimal("N/A")
    assert val == Decimal("0.0000")
    assert issue == "PARSE_ERROR"
