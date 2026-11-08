"""Character/Word Error Rate computation for OCR quality verification.

Standard Levenshtein edit-distance based CER/WER, as used across the OCR
literature (e.g. ICDAR robustness benchmarks): the minimum number of
substitutions/deletions/insertions to turn the hypothesis into the
reference, normalized by the reference length.
"""


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


def compute_cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate. Returns 0.0 for two empty strings (nothing to
    get wrong), and 1.0 when the reference is non-empty but there is no
    hypothesis text at all (100% of the reference is missing).
    """
    ref_chars = list(reference)
    hyp_chars = list(hypothesis)
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    return _levenshtein_distance(ref_chars, hyp_chars) / len(ref_chars)


def compute_wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate, tokenizing on whitespace."""
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return _levenshtein_distance(ref_words, hyp_words) / len(ref_words)


def compute_cer_wer(reference: str, hypothesis: str) -> dict[str, float]:
    return {
        "cer": round(compute_cer(reference, hypothesis), 4),
        "wer": round(compute_wer(reference, hypothesis), 4),
    }
