from benchmarks.scripts.ocr_metrics import compute_cer, compute_cer_wer, compute_wer


def test_identical_strings_have_zero_error():
    assert compute_cer("Công ty TNHH", "Công ty TNHH") == 0.0
    assert compute_wer("Công ty TNHH", "Công ty TNHH") == 0.0


def test_empty_hypothesis_against_nonempty_reference_is_total_error():
    assert compute_cer("Công ty", "") == 1.0
    assert compute_wer("Công ty", "") == 1.0


def test_both_empty_is_zero_error():
    assert compute_cer("", "") == 0.0
    assert compute_wer("", "") == 0.0


def test_cer_counts_single_character_substitution():
    # "Công" -> "Cong": one character substitution (ô -> o) out of 4 chars.
    assert compute_cer("Công", "Cong") == 0.25


def test_wer_counts_whole_word_differences():
    ref = "Công ty TNHH Dịch vụ Vệ sinh"
    hyp = "Cong ty TNHH Dich vu Ve sinh"
    result = compute_wer(ref, hyp)
    # 4 of 7 reference words lose their diacritics (Công, Dịch, vụ, Vệ);
    # "ty", "TNHH", "sinh" already had none to lose.
    assert result == 4 / 7


def test_compute_cer_wer_returns_both_metrics():
    result = compute_cer_wer("ABC", "ABD")
    assert result == {"cer": round(1 / 3, 4), "wer": 1.0}
