"""Immutable benchmark run artifact: pins inputs (git, manifest hash, provider) next to results."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
import uuid


def build_run_artifact(
    cases: list[dict[str, Any]],
    manifest_path: Path,
    git_sha: str,
    git_dirty: bool,
    provider: dict[str, str],
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    count = len(cases)

    def mean(key: str) -> float:
        return round(sum(case[key] for case in cases) / count, 4) if count else 0.0

    latencies = [case["latency_ms"] for case in cases]
    return {
        "run_id": f"{created_at:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}",
        "created_at": created_at.isoformat(),
        "git": {"sha": git_sha, "dirty": git_dirty},
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "provider": provider,
        "summary": {
            "cases": count,
            "header_exact_match": mean("header_exact_match"),
            "lines_f1": mean("lines_f1"),
            "mean_latency_ms": round(sum(latencies) / count, 1) if count else 0.0,
            "max_latency_ms": max(latencies, default=0.0),
            "vision_calls": sum(1 for case in cases if case.get("used_vision")),
            "total_cost_usd": round(sum(case.get("cost_usd") or 0.0 for case in cases), 6),
            "extraction_verified_cases": sum(
                1 for case in cases if not case.get("extraction_blockers")
            ),
            **_stp_summary(cases),
        },
        "cases": cases,
    }


def _stp_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """STP/review rates; a false auto-accept is a system approval of data that differs from GT."""
    gated = [case for case in cases if "gates" in case]
    if not gated:
        return {}
    approved = [case for case in gated if case["gates"]["accounting_approved"]]
    reviewed = [case for case in gated if not case["gates"]["accounting_approved"]]
    return {
        "stp_rate": round(len(approved) / len(gated), 4),
        "review_rate": round(len(reviewed) / len(gated), 4),
        "false_auto_accept": sum(
            1 for case in approved if case["header_exact_match"] < 1 or case["lines_f1"] < 1
        ),
        "matching_cleared_cases": sum(1 for case in gated if case["gates"]["matching_cleared"]),
        "review_fields_per_reviewed_case": round(
            sum(len(case.get("extraction_blockers", [])) for case in reviewed) / len(reviewed), 2
        )
        if reviewed
        else 0.0,
    }
