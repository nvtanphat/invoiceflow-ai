"""Accent-free label vocabulary of Vietnamese invoice summary fields (TT78 layouts)."""

# Longest labels first so "tong cong tien thanh toan" is not consumed as "tong cong".
TOTAL_LABELS: dict[str, tuple[str, ...]] = {
    "subtotal": (
        "cong tien hang hoa dich vu",
        "tong tien truoc thue",
        "cong tien hang",
        "tong tien hang",
        "tien hang",
        "subtotal",
    ),
    "tax_total": (
        "tong tien thue gtgt",
        "tien thue gtgt",
        "tong tien thue",
        "thue gtgt",
        "vat amount",
        "tax total",
    ),
    "amount_payable": (
        "tong cong tien thanh toan",
        "tong tien thanh toan",
        "tong thanh toan",
        "tong cong",
        "grand total",
        "total amount",
    ),
}

# Labels of per-line numeric values in text (non-table) invoice layouts.
LINE_LABELS: dict[str, tuple[str, ...]] = {
    "qty": ("so luong", "quantity", "qty", "sl"),
    "unit_price": ("don gia", "unit price"),
    "line_amount": ("thanh tien", "line amount"),
}
