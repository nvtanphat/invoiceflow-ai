import hashlib
import json

from benchmarks.scripts.run_artifact import build_run_artifact


def test_run_artifact_pins_inputs_and_summarises_cases(tmp_path):
    manifest = tmp_path / "casebook_manifest.json"
    manifest.write_text('[{"case_id": "C1"}]', encoding="utf-8")
    cases = [
        {
            "case_id": "C1",
            "header_exact_match": 0.5,
            "lines_f1": 1.0,
            "latency_ms": 10.0,
            "cost_usd": 0.002,
            "used_vision": True,
            "extraction_blockers": ["MISSING_FIELD_EVIDENCE: subtotal"],
        },
        {
            "case_id": "C2",
            "header_exact_match": 1.0,
            "lines_f1": 0.5,
            "latency_ms": 30.0,
            "cost_usd": 0.0,
            "used_vision": False,
            "extraction_blockers": [],
        },
    ]

    artifact = build_run_artifact(
        cases=cases,
        manifest_path=manifest,
        git_sha="abc123",
        git_dirty=True,
        provider={"model_id": "m", "base_url": "u"},
    )

    assert artifact["run_id"]
    assert artifact["git"] == {"sha": "abc123", "dirty": True}
    assert artifact["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    summary = artifact["summary"]
    assert summary["cases"] == 2
    assert summary["header_exact_match"] == 0.75
    assert summary["lines_f1"] == 0.75
    assert summary["vision_calls"] == 1
    assert summary["total_cost_usd"] == 0.002
    assert summary["extraction_verified_cases"] == 1
    assert summary["max_latency_ms"] == 30.0
    json.dumps(artifact)


def test_run_artifact_reports_stp_review_and_false_auto_accept(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text("[]", encoding="utf-8")

    def case(case_id, header, approved, matching, blockers):
        return {
            "case_id": case_id,
            "header_exact_match": header,
            "lines_f1": 1.0,
            "latency_ms": 1.0,
            "cost_usd": 0.0,
            "used_vision": False,
            "extraction_blockers": blockers,
            "gates": {
                "extraction_verified": not blockers,
                "matching_cleared": matching,
                "accounting_approved": approved,
            },
        }

    cases = [
        case("ok", 1.0, True, True, []),
        case("wrong-but-approved", 0.9, True, True, []),
        case("review", 0.8, False, False, ["a", "b", "c"]),
        case("variance", 1.0, False, False, []),
    ]

    summary = build_run_artifact(
        cases=cases,
        manifest_path=manifest,
        git_sha="s",
        git_dirty=False,
        provider={},
    )["summary"]

    assert summary["stp_rate"] == 0.5
    assert summary["review_rate"] == 0.5
    assert summary["false_auto_accept"] == 1
    assert summary["matching_cleared_cases"] == 2
    assert summary["review_fields_per_reviewed_case"] == 1.5
