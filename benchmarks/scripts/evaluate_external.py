"""Benchmark the production pipeline on independent public datasets.

    python benchmarks/scripts/evaluate_external.py --split dev --output <path outside git>

Datasets are read from ``--data-dir`` (default ``.local/datasets``, gitignored); see
``external_datasets.py`` for sources, licences and the dev/holdout split. The artifact
records git state, dataset/split, per-case metrics and summaries; it is a local output
and is never committed.

Safety is measured at field level because these documents carry no Vietnamese tax id
and no PO/GRN, so the document-level gates correctly never clear them: a *false field
accept* is a critical field the evidence gate would let through unreviewed whose value
differs from ground truth.
"""

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Optional

import numpy as np
import psutil

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from benchmarks.scripts.evaluator import (  # noqa: E402
    compute_line_items_f1,
    compute_table_extraction_quality,
)
from benchmarks.scripts.external_datasets import DATASETS, ExternalCase, load_cases  # noqa: E402
from benchmarks.scripts.ocr_metrics import compute_cer, compute_wer  # noqa: E402
from invoiceflow.application.processing.service import DocumentAIService  # noqa: E402
from invoiceflow.config import get_settings  # noqa: E402
from invoiceflow.domain.invoices.evidence_gate import (  # noqa: E402
    automation_blockers,
    review_items,
)
from invoiceflow.domain.invoices.models import InvoiceAggregate  # noqa: E402

_BLOCKED_PATH = re.compile(r":\s*(\S+)")


def _same_value(gt: Optional[str], pred: Any) -> bool:
    if gt is None or pred is None:
        return False
    try:
        return Decimal(str(gt)) == Decimal(str(pred))
    except InvalidOperation:
        return str(gt).strip().lower() == str(pred).strip().lower()


def predicted_header(invoice: InvoiceAggregate) -> dict[str, Optional[str]]:
    def text(value: Any) -> Optional[str]:
        return None if value is None else str(value)

    return {
        "invoice_number": text(invoice.invoice_number),
        "issue_date": text(invoice.issue_date),
        "subtotal": text(invoice.subtotal),
        "tax_total": text(invoice.tax_total),
        "amount_payable": text(invoice.amount_payable),
    }


def predicted_lines(invoice: InvoiceAggregate) -> list[dict[str, Optional[str]]]:
    def text(value: Any) -> Optional[str]:
        return None if value is None else str(value)

    return [
        {
            "sku": line.sku_ref or "",
            "description": line.description or "",
            "qty": text(line.qty),
            "unit_price": text(line.unit_price),
            "line_amount": text(line.line_amount),
        }
        for line in invoice.lines
    ]


def unreviewed_paths(invoice: InvoiceAggregate) -> set[str]:
    """Field paths with evidence that the automation gate does not block."""
    blocked = {
        match.group(1)
        for blocker in automation_blockers(invoice)
        if (match := _BLOCKED_PATH.search(blocker))
    }
    return {record.field_path for record in invoice.evidence} - blocked


def bbox_hit(invoice: InvoiceAggregate, path: str, gt_box: tuple[float, ...]) -> Optional[bool]:
    """Centre of the evidence box inside the annotated box (10% margin); None if no box."""
    record = next((r for r in invoice.evidence if r.field_path == path and r.bbox), None)
    if record is None or record.bbox is None:
        return None
    x0, y0, x1, y1 = gt_box
    mx, my = (x1 - x0) * 0.1, (y1 - y0) * 0.1
    cx = (record.bbox.x0 + record.bbox.x1) / 2
    cy = (record.bbox.y0 + record.bbox.y1) / 2
    return (x0 - mx) <= cx <= (x1 + mx) and (y0 - my) <= cy <= (y1 + my)


def evaluate_case(service: DocumentAIService, case: ExternalCase) -> dict[str, Any]:
    started = time.perf_counter()
    result = asyncio.run(
        service.process_document(
            tenant_id="external-benchmark",
            document_id=case.case_id,
            filename=case.filename,
            content=case.image_bytes,
        )
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    invoice = result.invoice_aggregate
    header = predicted_header(invoice)
    lines = predicted_lines(invoice)
    evaluated_fields = [name for name, value in case.header.items() if value is not None]
    correct = [name for name in evaluated_fields if _same_value(case.header[name], header[name])]
    unreviewed = unreviewed_paths(invoice)
    false_accepts = [
        name for name in evaluated_fields if name in unreviewed and name not in correct
    ]
    precision, recall, f1 = compute_line_items_f1(case.lines, lines)
    table = compute_table_extraction_quality(case.lines, lines)
    blockers = automation_blockers(invoice)

    record: dict[str, Any] = {
        "case_id": case.case_id,
        "dataset": case.dataset.name,
        "route": str(getattr(result.route, "value", result.route)),
        "latency_ms": latency_ms,
        "cost_usd": result.cost_usd,
        "used_vision": result.used_vision,
        # A failed provider call still sets used_vision; keep the reason so runs whose
        # Vision availability differs are never compared as if they were equivalent.
        "provider_failure": result.provider_failure,
        "fields_evaluated": evaluated_fields,
        "fields_correct": correct,
        "field_mismatches": {
            name: {"gt": case.header[name], "pred": header[name]}
            for name in evaluated_fields
            if name not in correct
        },
        "fields_unreviewed": sorted(name for name in evaluated_fields if name in unreviewed),
        "false_field_accepts": false_accepts,
        "gt_lines": len(case.lines),
        "pred_lines": len(lines),
        "lines_precision": round(precision, 4),
        "lines_recall": round(recall, 4),
        "lines_f1": round(f1, 4),
        "table_f1": round(table["table_f1"], 4),
        "extraction_verified": not blockers,
        "review_item_count": len(review_items(invoice.evidence, len(invoice.lines))),
    }
    record["false_auto_accept"] = record["extraction_verified"] and (
        bool(record["field_mismatches"]) or f1 < 1.0
    )
    if case.reference_text:
        record["cer"] = round(compute_cer(case.reference_text, result.full_text), 4)
        record["wer"] = round(compute_wer(case.reference_text, result.full_text), 4)
    if "amount_payable" in case.field_boxes and "amount_payable" in correct:
        record["amount_payable_bbox_hit"] = bbox_hit(
            invoice, "amount_payable", case.field_boxes["amount_payable"]
        )
    return record


def _rate(values: list[bool]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = sum(len(c["fields_evaluated"]) for c in cases)
    per_field: dict[str, dict[str, int]] = {}
    for case in cases:
        for name in case["fields_evaluated"]:
            stats = per_field.setdefault(name, {"evaluated": 0, "correct": 0})
            stats["evaluated"] += 1
            stats["correct"] += name in case["fields_correct"]
    latencies = [c["latency_ms"] for c in cases]
    bbox = [
        c["amount_payable_bbox_hit"] for c in cases if c.get("amount_payable_bbox_hit") is not None
    ]
    with_text = [c for c in cases if "cer" in c]
    return {
        "cases": len(cases),
        "header_field_accuracy": round(sum(len(c["fields_correct"]) for c in cases) / evaluated, 4)
        if evaluated
        else None,
        "per_field_accuracy": {
            name: round(s["correct"] / s["evaluated"], 4) for name, s in sorted(per_field.items())
        },
        "lines_f1": round(float(np.mean([c["lines_f1"] for c in cases])), 4),
        "table_f1": round(float(np.mean([c["table_f1"] for c in cases])), 4),
        "cer": round(float(np.mean([c["cer"] for c in with_text])), 4) if with_text else None,
        "wer": round(float(np.mean([c["wer"] for c in with_text])), 4) if with_text else None,
        "amount_payable_bbox_accuracy": _rate(bbox),
        "extraction_verified_rate": _rate([c["extraction_verified"] for c in cases]),
        "false_auto_accept_docs": sum(c["false_auto_accept"] for c in cases),
        "unreviewed_fields": sum(len(c["fields_unreviewed"]) for c in cases),
        "false_field_accepts": sum(len(c["false_field_accepts"]) for c in cases),
        "mean_review_items": round(float(np.mean([c["review_item_count"] for c in cases])), 2),
        "mean_latency_ms": round(float(np.mean(latencies)), 1),
        "p95_latency_ms": round(float(np.percentile(latencies, 95)), 1),
        "vision_calls": sum(c["used_vision"] for c in cases),
        "vision_failures": sum(1 for c in cases if c.get("provider_failure")),
        "total_cost_usd": round(sum(c["cost_usd"] or 0.0 for c in cases), 6),
    }


def _git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT_DIR, capture_output=True, text=True, check=False
        ).stdout.strip()

    return {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def _current_rss_mb() -> float:
    return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)


def _completed_cases(progress: Path) -> dict[str, dict[str, Any]]:
    if not progress.exists():
        return {}
    records = (json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines())
    return {record["case_id"]: record for record in records}


def _peak_rss_mb() -> float:
    info = psutil.Process().memory_info()
    return round((getattr(info, "peak_wset", None) or info.rss) / (1024 * 1024), 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "holdout"], required=True)
    parser.add_argument("--datasets", nargs="+", default=sorted(DATASETS), choices=sorted(DATASETS))
    parser.add_argument("--limit", type=int, help="First N documents per dataset (deterministic)")
    parser.add_argument("--data-dir", type=Path, default=ROOT_DIR / ".local" / "datasets")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    settings = get_settings()
    service = DocumentAIService()
    # One JSON line per finished case, so a crash (e.g. OOM) loses nothing and a rerun
    # resumes after the last completed document.
    progress = args.output.with_suffix(".jsonl")
    progress.parent.mkdir(parents=True, exist_ok=True)
    done = _completed_cases(progress)
    results: dict[str, list[dict[str, Any]]] = {name: [] for name in args.datasets}
    for record in done.values():
        if record["dataset"] in results:
            results[record["dataset"]].append(record)
    for name in args.datasets:
        for case in load_cases(args.data_dir, name, args.split, args.limit):
            if case.case_id in done:
                continue
            record = evaluate_case(service, case)
            record["rss_mb_after"] = _current_rss_mb()
            results[name].append(record)
            with progress.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(
                f"{record['case_id']}: fields {len(record['fields_correct'])}/"
                f"{len(record['fields_evaluated'])} lines_f1={record['lines_f1']} "
                f"{record['latency_ms']:.0f} ms",
                flush=True,
            )

    artifact = {
        "run_id": f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-external-{args.split}",
        "git": _git_state(),
        "split": args.split,
        "limit": args.limit,
        "datasets": {
            name: {
                "kind": DATASETS[name].document_kind,
                "provenance": DATASETS[name].provenance,
                "licence": DATASETS[name].licence,
                "summary": summarize(cases),
            }
            for name, cases in results.items()
        },
        "provider": {
            "llm_provider": settings.LLM_PROVIDER,
            "vision_configured": bool(settings.OPENAI_API_KEY or settings.GEMINI_API_KEY),
            "ocr_engine": settings.OCR_ENGINE,
            "ocr_dpi": settings.OCR_DPI,
        },
        "peak_rss_mb": _peak_rss_mb(),
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v["summary"] for k, v in artifact["datasets"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
