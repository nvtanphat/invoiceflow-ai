from benchmarks.scripts.external_datasets import (
    cord_field_boxes,
    cord_ground_truth,
    cord_reference_text,
    parse_comma_decimal,
    parse_cord_amount,
    parse_us_date,
    sparrow_ground_truth,
)


def _word(text, x, y, row):
    quad = {
        "x1": x,
        "x2": x + 10,
        "x3": x + 10,
        "x4": x,
        "y1": y,
        "y2": y,
        "y3": y + 8,
        "y4": y + 8,
    }
    return {"text": text, "quad": quad, "row_id": row}


def test_cord_amounts_use_separators_only_for_thousands():
    assert parse_cord_amount("60.000") == "60000"
    assert parse_cord_amount("1,500") == "1500"
    assert parse_cord_amount("-60.000") == "-60000"
    assert parse_cord_amount("Rp") is None
    assert parse_cord_amount(None) is None


def test_sparrow_amounts_use_decimal_comma():
    assert parse_comma_decimal("$ 889,20") == "889.2"
    assert parse_comma_decimal("1 234,50") == "1234.5"
    assert parse_comma_decimal("2,00") == "2"
    assert parse_comma_decimal("") is None


def test_us_dates_become_iso():
    assert parse_us_date("09/18/2015") == "2015-09-18"
    assert parse_us_date("2015-09-18") is None


def test_cord_menu_as_single_dict_or_list_maps_to_lines_and_totals():
    gt = {
        "gt_parse": {
            "menu": {"nm": "TICKET", "cnt": "2", "price": "60.000"},
            "sub_total": {"subtotal_price": "60.000", "tax_price": "5.455"},
            "total": {"total_price": "60.000"},
        }
    }
    header, lines = cord_ground_truth(gt)
    assert header == {"subtotal": "60000", "tax_total": "5455", "amount_payable": "60000"}
    assert lines == [
        {"sku": "", "description": "TICKET", "qty": "2", "unit_price": None, "line_amount": "60000"}
    ]


def test_cord_reference_text_orders_rows_and_words_and_total_box():
    gt = {
        "valid_line": [
            {"category": "total.total_price", "words": [_word("60.000", 50, 100, 2)]},
            {"category": "menu.nm", "words": [_word("TICKET", 30, 10, 1), _word("A", 5, 11, 1)]},
        ]
    }
    assert cord_reference_text(gt) == "A TICKET\n60.000"
    assert cord_field_boxes(gt) == {"amount_payable": (50, 100, 60, 108)}


def test_sparrow_header_items_and_summary():
    gt = {
        "gt_parse": {
            "header": {"invoice_no": "97159829", "invoice_date": "09/18/2015"},
            "items": [
                {
                    "item_desc": "Chess table",
                    "item_qty": "2,00",
                    "item_net_price": "444,60",
                    "item_net_worth": "889,20",
                }
            ],
            "summary": {
                "total_net_worth": "$ 889,20",
                "total_vat": "$ 88,92",
                "total_gross_worth": "$ 978,12",
            },
        }
    }
    header, lines = sparrow_ground_truth(gt)
    assert header == {
        "invoice_number": "97159829",
        "issue_date": "2015-09-18",
        "subtotal": "889.2",
        "tax_total": "88.92",
        "amount_payable": "978.12",
    }
    assert lines[0]["qty"] == "2" and lines[0]["line_amount"] == "889.2"


def test_sparrow_flat_record_without_wrappers():
    gt = {
        "gt_parse": {
            "invoice_no": "1",
            "invoice_date": "04/11/2021",
            "item_desc": "Lamp",
            "item_qty": "1,00",
            "item_net_price": "10,00",
            "item_net_worth": "10,00",
            "total_net_worth": "$ 10,00",
            "total_vat": "$ 1,00",
            "total_gross_worth": "$ 11,00",
        }
    }
    header, lines = sparrow_ground_truth(gt)
    assert header["invoice_number"] == "1" and header["issue_date"] == "2021-04-11"
    assert header["amount_payable"] == "11"
    assert [line["description"] for line in lines] == ["Lamp"]
