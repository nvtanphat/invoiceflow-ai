"""Character/Word Error Rate computation for OCR quality verification.

Standard Levenshtein edit-distance based CER/WER, as used across the OCR
literature (e.g. ICDAR robustness benchmarks): the minimum number of
substitutions/deletions/insertions to turn the hypothesis into the
reference, normalized by the reference length.

Includes unicode NFC normalization, whitespace collapsing, soft-hyphen
normalization, and Vietnamese diacritic folding for dual CER reporting.
"""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def fold_vietnamese(text: str) -> str:
    """Lowercase, accent-free form for label and unaccented CER matching."""
    cleaned = text.replace("đ", "d").replace("Đ", "d")
    decomposed = unicodedata.normalize("NFKD", cleaned)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def normalize_text_for_cer(text: str) -> str:
    """Normalizes text for robust CER/WER comparison.

    - Decomposes and recomposes to Unicode NFC.
    - Normalizes soft hyphens (\\u00ad) to standard hyphens (-).
    - Collapses all whitespace (newlines, tabs, multiple spaces) into a single space.
    - Strips leading and trailing whitespace.
    """
    if not text:
        return ""
    norm = unicodedata.normalize("NFC", text)
    norm = norm.replace("\u00ad", "-")
    norm = _WHITESPACE.sub(" ", norm).strip()
    return norm


def _levenshtein_distance(reference: list, hypothesis: list) -> int:
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)

    previous_row = list(range(len(hypothesis) + 1))
    for i, r_token in enumerate(reference, start=1):
        current_row = [i] + [0] * len(hypothesis)
        for j, h_token in enumerate(hypothesis, start=1):
            cost = 0 if r_token == h_token else 1
            current_row[j] = min(
                previous_row[j] + 1,  # deletion
                current_row[j - 1] + 1,  # insertion
                previous_row[j - 1] + cost,  # substitution
            )
        previous_row = current_row
    return previous_row[-1]


def compute_cer(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """Character Error Rate. Returns 0.0 for two empty strings, and 1.0 when
    the reference is non-empty but hypothesis is empty.
    """
    ref_str = normalize_text_for_cer(reference) if normalize else reference
    hyp_str = normalize_text_for_cer(hypothesis) if normalize else hypothesis

    ref_chars = list(ref_str)
    hyp_chars = list(hyp_str)
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    return _levenshtein_distance(ref_chars, hyp_chars) / len(ref_chars)


def compute_wer(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """Word Error Rate, tokenizing on whitespace."""
    ref_str = normalize_text_for_cer(reference) if normalize else reference
    hyp_str = normalize_text_for_cer(hypothesis) if normalize else hypothesis

    ref_words = ref_str.split()
    hyp_words = hyp_str.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return _levenshtein_distance(ref_words, hyp_words) / len(ref_words)


def compute_cer_wer(reference: str, hypothesis: str, normalize: bool = True) -> dict[str, float]:
    return {
        "cer": round(compute_cer(reference, hypothesis, normalize=normalize), 4),
        "wer": round(compute_wer(reference, hypothesis, normalize=normalize), 4),
    }


def compute_dual_cer_wer(reference: str, hypothesis: str) -> dict[str, float]:
    """Computes dual CER/WER: both accented and diacritic-folded (unaccented).

    This isolates transcription/character recognition errors from diacritic drop errors.
    """
    accented = compute_cer_wer(reference, hypothesis, normalize=True)
    ref_folded = fold_vietnamese(normalize_text_for_cer(reference))
    hyp_folded = fold_vietnamese(normalize_text_for_cer(hypothesis))
    unaccented = compute_cer_wer(ref_folded, hyp_folded, normalize=False)

    return {
        "cer": accented["cer"],
        "wer": accented["wer"],
        "cer_unaccented": unaccented["cer"],
        "wer_unaccented": unaccented["wer"],
    }
