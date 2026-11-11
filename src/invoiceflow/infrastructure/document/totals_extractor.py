"""Label-driven extraction of invoice summary totals from document text.

Keyword-per-field extraction follows the approach of invoice2data templates (MIT): labels
are matched accent-insensitively because OCR frequently drops Vietnamese diacritics, and
several totals may share one OCR line. The last occurrence wins since the summary block
follows the line items.
"""

from dataclasses import dataclass
import re
import unicodedata

from invoiceflow.domain.documents.value_parsing import fold_vietnamese
from invoiceflow.domain.invoices.field_labels import TOTAL_LABELS

# An amount must end cleanly: OCR glyph swaps such as "6ooo0000" are unreadable, never "6".
_NUMBER = r"(\d[\d.,]*(?:\s\d{3})*)(?![\w.,])(?!\s*%)"
_CURRENCY_SYMBOL = r"(?:[$€£¥₫]\s*)?"
# Another amount right after the matched one (same line, no label between): the label
# does not identify which of the amounts it names, e.g. "Total 196,97 19,70 216,67".
_FOLLOWING_AMOUNT = re.compile(rf"[ \t]*{_CURRENCY_SYMBOL}\d")


@dataclass(frozen=True)
class TotalMatch:
    raw: str
    label: str
    start: int


def _label_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    # Optional "(10%)" rate annotation and ":" between label and amount.
    return re.compile(
        rf"(?<![a-z])({alternation})(?:\s*\([^)]*\))?\s*:?\s*{_CURRENCY_SYMBOL}{_NUMBER}"
    )


_PATTERNS = {field: _label_pattern(labels) for field, labels in TOTAL_LABELS.items()}
_ALL_LABELS = _label_pattern(tuple(label for labels in TOTAL_LABELS.values() for label in labels))


def extract_invoice_totals(text: str) -> dict[str, TotalMatch]:
    text = unicodedata.normalize("NFC", text)
    folded = fold_vietnamese(text)
    if len(folded) != len(text):
        # Folding must keep offsets aligned so raw digits are sliced from the source text.
        folded = text.lower()

    owners = {match.start(1): match.group(1) for match in _ALL_LABELS.finditer(folded)}
    totals: dict[str, TotalMatch] = {}
    for field, pattern in _PATTERNS.items():
        for match in pattern.finditer(folded):
            # A shorter label of another field inside a longer label (e.g. "thue gtgt"
            # within "tien thue gtgt") is not a separate occurrence.
            if owners.get(match.start(1)) != match.group(1):
                continue
            if _FOLLOWING_AMOUNT.match(folded, match.end(2)):
                continue
            totals[field] = TotalMatch(
                raw=text[match.start(2) : match.end(2)].strip(),
                label=match.group(1),
                start=match.start(1),
            )
    return totals
