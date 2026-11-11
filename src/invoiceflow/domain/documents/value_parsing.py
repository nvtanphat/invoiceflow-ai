"""Pure parsing of values as printed on Vietnamese invoices (numbers, accent-insensitive text)."""

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Optional
import unicodedata

_CURRENCY_MARKS = re.compile(r"(?i)(?:vnd|vnđ|usd|eur|[₫đ$])")
_SPACED_THOUSANDS = re.compile(r"(\d)\s+(\d{3})\b")
# OCR inserts spaces around separators ("20, 000", "89 . 100"); left in place they push the
# value into the decimal branch and 20,000 becomes 20.
_SPACED_SEPARATOR = re.compile(r"(?<=\d)\s*([.,])\s*(?=\d)")
_ZERO = Decimal("0.0000")
_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_DMY_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})(?!\d)")
_VN_WORDED_DATE = re.compile(r"ngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*(\d{4})")


def fold_vietnamese(text: str) -> str:
    """Lowercase, accent-free form for label matching (OCR often drops diacritics)."""
    cleaned = text.replace("đ", "d").replace("Đ", "d").replace("\u00ad", "-")
    decomposed = unicodedata.normalize("NFKD", cleaned)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def parse_vn_decimal(value: Any, is_qty: bool = False) -> tuple[Decimal, Optional[str]]:
    """Parse VN ("12.000.000,50") and US ("12,000,000.50") notations.

    Returns (value, issue). Ambiguous groupings are reported, never silently resolved.
    """
    if not value or not str(value).strip():
        return _ZERO, None
    s = str(value).strip().replace(" ", " ")
    s = _CURRENCY_MARKS.sub("", s).strip()
    s = _SPACED_SEPARATOR.sub(r"\1", s)
    s = _SPACED_THOUSANDS.sub(r"\1\2", s)
    # A trailing "%" marks a percentage; strip it before the separator heuristics so
    # "10.00%" is not misread as a thousands-grouped "10,000".
    if s.endswith("%"):
        s = s[:-1].strip()
    if not re.search(r"\d", s):
        return _ZERO, "PARSE_ERROR"

    s, issue = _normalise_separators(s, is_qty)
    try:
        return Decimal(re.sub(r"[^\d.-]", "", s)), issue
    except InvalidOperation:
        return _ZERO, "PARSE_ERROR"


def _normalise_separators(s: str, is_qty: bool) -> tuple[str, Optional[str]]:
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            return s.replace(".", "").replace(",", "."), None
        return s.replace(",", ""), None
    if "." in s:
        parts = s.split(".")
        if is_qty and len(parts) == 2:
            return s, None
        if all(len(p) == 3 for p in parts[1:]):
            return s.replace(".", ""), None
        if len(parts) == 2:
            return s, None
        return s, "AMBIGUOUS_NUMBER"
    if "," in s:
        parts = s.split(",")
        if is_qty and len(parts) == 2 and len(parts[1]) == 3:
            return s.replace(",", ""), "AMBIGUOUS_NUMBER"
        if all(len(p) == 3 for p in parts[1:]):
            return s.replace(",", ""), None
        if len(parts) == 2:
            return s.replace(",", "."), None
        return s.replace(",", ""), "AMBIGUOUS_NUMBER"
    return s, None


def normalize_tax_id(value: str) -> str:
    """Vietnamese MST without layout characters: 10 digits, optional '-NNN' branch suffix."""
    cleaned = value.replace("\u00ad", "-")
    return re.sub(r"[^\d-]", "", cleaned)


def parse_printed_date(value: str) -> Optional[date]:
    """Date as printed on invoices: ISO, dd/mm/yyyy (also '.' or '-'), or 'ngày d tháng m năm y'."""
    folded = fold_vietnamese(value)
    iso = _ISO_DATE.search(folded)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
    else:
        match = _DMY_DATE.search(folded) or _VN_WORDED_DATE.search(folded)
        if match is None:
            return None
        day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
