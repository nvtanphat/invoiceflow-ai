import csv
import io
import json
from decimal import Decimal
from typing import Any, List
from openpyxl import Workbook


def sanitize_csv_cell(val: Any) -> str:
    """Escapes potential formula injection prefixes (=, +, -, @) with a leading single quote."""
    if val is None:
        return ""
    text = str(val)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


class DocumentExporter:
    @staticmethod
    def to_csv(invoices: List[dict]) -> str:
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Header
        writer.writerow([
            "Invoice ID",
            "Supplier Name",
            "Supplier Tax ID",
            "Invoice Number",
            "Invoice Series",
            "Issue Date",
            "Currency",
            "Subtotal",
            "Tax Total",
            "Amount Payable",
            "Status",
        ])

        for inv in invoices:
            writer.writerow([
                sanitize_csv_cell(inv.get("id")),
                sanitize_csv_cell(inv.get("supplier_name")),
                sanitize_csv_cell(inv.get("supplier_tax_id")),
                sanitize_csv_cell(inv.get("invoice_number")),
                sanitize_csv_cell(inv.get("invoice_series")),
                sanitize_csv_cell(inv.get("issue_date")),
                sanitize_csv_cell(inv.get("currency", "VND")),
                sanitize_csv_cell(str(inv.get("subtotal", "0.00"))),
                sanitize_csv_cell(str(inv.get("tax_total", "0.00"))),
                sanitize_csv_cell(str(inv.get("amount_payable", "0.00"))),
                sanitize_csv_cell(inv.get("status")),
            ])

        return output.getvalue()

    @staticmethod
    def to_json(invoices: List[dict]) -> str:
        return json.dumps(invoices, indent=2, default=str)

    @staticmethod
    def to_excel(invoices: List[dict]) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Invoices"

        headers = [
            "Invoice ID",
            "Supplier Name",
            "Supplier Tax ID",
            "Invoice Number",
            "Invoice Series",
            "Issue Date",
            "Currency",
            "Subtotal",
            "Tax Total",
            "Amount Payable",
            "Status",
        ]
        ws.append(headers)

        for inv in invoices:
            ws.append([
                str(inv.get("id", "")),
                sanitize_csv_cell(inv.get("supplier_name", "")),
                sanitize_csv_cell(inv.get("supplier_tax_id", "")),
                sanitize_csv_cell(inv.get("invoice_number", "")),
                sanitize_csv_cell(inv.get("invoice_series", "")),
                str(inv.get("issue_date", "")),
                str(inv.get("currency", "VND")),
                float(inv.get("subtotal", 0)),
                float(inv.get("tax_total", 0)),
                float(inv.get("amount_payable", 0)),
                str(inv.get("status", "")),
            ])

        stream = io.BytesIO()
        wb.save(stream)
        return stream.getvalue()
