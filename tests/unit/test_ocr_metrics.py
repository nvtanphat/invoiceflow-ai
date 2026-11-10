from benchmarks.scripts.ocr_metrics import (
    compute_cer,
    compute_cer_wer,
    compute_dual_cer_wer,
    compute_wer,
    normalize_text_for_cer,
)


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
    assert result == 4 / 7


def test_compute_cer_wer_returns_both_metrics():
    result = compute_cer_wer("ABC", "ABD")
    assert result == {"cer": round(1 / 3, 4), "wer": 1.0}


def test_normalize_text_for_cer_collapses_newlines_and_whitespace():
    raw = "Ky hieu: 1C26TEE\n\n  So hoa don: 0045231 \r\n Ngay lap: 2026-03-01\t"
    expected = "Ky hieu: 1C26TEE So hoa don: 0045231 Ngay lap: 2026-03-01"
    assert normalize_text_for_cer(raw) == expected


def test_normalize_text_for_cer_replaces_soft_hyphens():
    raw = "2026\u00ad03\u00ad01 and ELEC\u00adTIER\u00ad1"
    expected = "2026-03-01 and ELEC-TIER-1"
    assert normalize_text_for_cer(raw) == expected


def test_cer_with_different_line_breaks_is_zero():
    ref = "Ky hieu: 1C26TEE\nSo hoa don: 0045231\nNgay lap: 2026-03-01"
    hyp = "Ky hieu: 1C26TEE So hoa don: 0045231 Ngay lap: 2026-03-01"
    assert compute_cer(ref, hyp, normalize=True) == 0.0
    assert compute_wer(ref, hyp, normalize=True) == 0.0


def test_dual_cer_wer_separates_accents_from_transcription_errors():
    ref = "Hóa đơn giá trị gia tăng"
    hyp = "Hoa don gia tri gia tang"
    res = compute_dual_cer_wer(ref, hyp)
    assert res["cer"] > 0.0
    assert res["wer"] > 0.0
    assert res["cer_unaccented"] == 0.0
    assert res["wer_unaccented"] == 0.0


def test_dual_cer_wer_empty_strings():
    res = compute_dual_cer_wer("", "")
    assert res["cer"] == 0.0
    assert res["wer"] == 0.0
    assert res["cer_unaccented"] == 0.0
    assert res["wer_unaccented"] == 0.0
