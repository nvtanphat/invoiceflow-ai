import asyncio
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List
import uuid

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from benchmarks.scripts.evaluator import evaluate_prediction  # noqa: E402
from benchmarks.scripts.run_benchmark import (  # noqa: E402
    get_demo_po_and_grn,
    get_fixture_file,
    load_manifest,
    run_b0_xml_direct,
    run_b4_pure_vision_llm,
)
from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute  # noqa: E402
from invoiceflow.application.reconciliation.matching_engine import MatchingEngine  # noqa: E402
from invoiceflow.config import get_settings  # noqa: E402
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceLine  # noqa: E402
from invoiceflow.domain.policies.models import TolerancePolicy  # noqa: E402
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser  # noqa: E402
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter  # noqa: E402
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector  # noqa: E402
from invoiceflow.infrastructure.document.table_extractor import StructureAwareTableExtractor  # noqa: E402
from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter  # noqa: E402


async def run_pipeline_variant(
    case: Dict[str, Any],
    file_path: Path,
    adapter: OpenAIAdapter,
    use_table_extractor: bool = True,
    use_ocr: bool = True,
    use_validation: bool = True,
    use_vision_fallback: bool = True,
    use_hybrid_routing: bool = True,
) -> Dict[str, Any]:
    start = time.perf_counter()
    with open(file_path, "rb") as f:
        content = f.read()

    # Route decision
    if not use_hybrid_routing:
        # Naive single route: treat everything as digital fast path
        route = ProcessingRoute.PDF_DIGITAL
    else:
        if file_path.suffix == ".xml":
            router = DocumentRouter()
            route = router.decide_route("xml", len(content))
        else:
            inspector = PDFInspector()
            profile = inspector.inspect(content)
            router = DocumentRouter()
            route = router.decide_route(
                detected_kind="pdf",
                file_size_bytes=len(content),
                pdf_classification=profile.classification,
                table_count=profile.table_count,
                has_rotated_pages=profile.has_rotated_pages,
            )

    header: Dict[str, Any] = {}
    lines: List[Dict[str, Any]] = []
    cost = 0.0000

    if route == ProcessingRoute.XML_DETERMINISTIC:
        res = run_b0_xml_direct(case, file_path)
        header = res["header"]
        lines = res["lines"]
    elif route == ProcessingRoute.VISION_FALLBACK and use_vision_fallback:
        res = await run_b4_pure_vision_llm(case, file_path, adapter)
        header = res["header"]
        lines = res["lines"]
        cost = res.get("cost_usd", 0.0)
    else:
        do_ocr = (route == ProcessingRoute.DOCLING_OCR_STRUCTURED) and use_ocr
        docling_adapter = DoclingAdapter()
        canonical_doc = docling_adapter.extract_canonical(
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            pdf_bytes=content,
            do_ocr=do_ocr,
        )

        if use_table_extractor:
            table_extractor = StructureAwareTableExtractor()
            extracted_lines = table_extractor.extract_lines(canonical_doc.tables)
            if extracted_lines:
                lines = [
                    {
                        "sku": line_item.sku or "",
                        "description": line_item.description,
                        "qty": str(line_item.qty),
                        "unit_price": str(line_item.unit_price),
                        "tax_rate": str(line_item.tax_rate) if line_item.tax_rate else None,
                        "line_amount": str(line_item.line_amount),
                    }
                    for line_item in extracted_lines
                ]

        full_text = "\n".join([el.text for el in canonical_doc.elements])
        parser = DigitalPDFParser()
        ext = parser.parse(full_text)
        header = {
            "supplier_tax_id": ext.supplier_tax_id or "",
            "supplier_name": ext.supplier_name or "",
            "buyer_tax_id": ext.buyer_tax_id or "",
            "buyer_name": ext.buyer_name or "",
            "invoice_number": ext.invoice_number or "",
            "invoice_series": ext.invoice_series or "",
            "issue_date": ext.issue_date or "",
            "currency": ext.currency,
            "subtotal": str(ext.subtotal),
            "tax_total": str(ext.tax_total),
            "amount_payable": str(ext.amount_payable),
        }
        if not lines:
            lines = [
                {
                    "sku": line.sku or "",
                    "description": line.description,
                    "qty": str(line.qty),
                    "unit_price": str(line.unit_price),
                    "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                    "line_amount": str(line.line_amount),
                }
                for line in ext.lines
            ]

    # Reconciliation with optional validation
    detected_discrepancies: List[str] = []
    po, receipts = get_demo_po_and_grn(header.get("supplier_tax_id"), case["case_id"])
    policy = TolerancePolicy(
        tenant_id=uuid.uuid4(),
        price_tolerance_pct=Decimal("0.02"),
        qty_tolerance_pct=Decimal("0.00"),
    )

    if lines and use_validation:
        inv_lines = [
            InvoiceLine(
                line_no=idx,
                sku_ref=item["sku"],
                description=item["description"],
                qty=Decimal(item["qty"]),
                unit_price=Decimal(item["unit_price"]),
                tax_rate=Decimal(item["tax_rate"]) if item.get("tax_rate") else None,
                line_amount=Decimal(item["line_amount"]),
            )
            for idx, item in enumerate(lines, start=1)
        ]
        invoice_agg = InvoiceAggregate(
            id=uuid.uuid4(),
            tenant_id=po.tenant_id,
            document_id=uuid.uuid4(),
            supplier_tax_id=header.get("supplier_tax_id"),
            invoice_number=header.get("invoice_number"),
            lines=inv_lines,
        )
        engine = MatchingEngine()
        report = engine.match_3_way(invoice_agg, po=po, receipts=receipts, policy=policy)
        for issue in report.issues:
            if "PRICE" in issue.code:
                detected_discrepancies.append("PRICE_MISMATCH")
            elif "QUANTITY" in issue.code or "QTY" in issue.code:
                detected_discrepancies.append("QUANTITY_MISMATCH")

    duration_ms = (time.perf_counter() - start) * 1000
    return {
        "case_id": case["case_id"],
        "header": header,
        "lines": lines,
        "detected_discrepancies": detected_discrepancies,
        "latency_ms": round(duration_ms, 2),
        "cost_usd": cost,
    }


async def run_ablation_suite() -> Dict[str, Any]:
    cases = load_manifest()
    settings = get_settings()
    adapter = OpenAIAdapter(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        model_id=settings.OPENAI_MODEL_ID,
        timeout=5.0,
        max_retries=0,
    )

    configurations = {
        "A0_FULL_HYBRID_SYSTEM": {
            "use_table_extractor": True,
            "use_ocr": True,
            "use_validation": True,
            "use_vision_fallback": True,
            "use_hybrid_routing": True,
            "desc": "Full hybrid pipeline with structure-aware table extraction, OCR & verification",
        },
        "A1_NO_TABLE_EXTRACTOR": {
            "use_table_extractor": False,
            "use_ocr": True,
            "use_validation": True,
            "use_vision_fallback": True,
            "use_hybrid_routing": True,
            "desc": "Without structure-aware table extraction (plain text regex fallback)",
        },
        "A2_NO_OCR": {
            "use_table_extractor": True,
            "use_ocr": False,
            "use_validation": True,
            "use_vision_fallback": True,
            "use_hybrid_routing": True,
            "desc": "Without local OCR on scanned/rotated documents",
        },
        "A3_NO_VALIDATION": {
            "use_table_extractor": True,
            "use_ocr": True,
            "use_validation": False,
            "use_vision_fallback": True,
            "use_hybrid_routing": True,
            "desc": "Without deterministic arithmetic sanity check & matching",
        },
        "A4_NO_VISION_FALLBACK": {
            "use_table_extractor": True,
            "use_ocr": True,
            "use_validation": True,
            "use_vision_fallback": False,
            "use_hybrid_routing": True,
            "desc": "Without Vision LLM fallback on difficult scans",
        },
        "A5_NO_HYBRID_ROUTING": {
            "use_table_extractor": True,
            "use_ocr": True,
            "use_validation": True,
            "use_vision_fallback": True,
            "use_hybrid_routing": False,
            "desc": "Without hybrid routing (uniform naive digital execution)",
        },
    }

    report: Dict[str, Any] = {
        "ablation_suite": "InvoiceFlow AI Core Architectural Ablations v1.0",
        "total_cases": len(cases),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ablations": {},
    }

    summary_rows = []
    results_dir = ROOT_DIR / "benchmarks" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    for a_id, cfg in configurations.items():
        print(f"[*] Running Ablation {a_id}: {cfg['desc']}...", flush=True)
        scores = []
        for c in cases:
            p = get_fixture_file(c["case_id"])
            pred = await run_pipeline_variant(
                case=c,
                file_path=p,
                adapter=adapter,
                use_table_extractor=cfg["use_table_extractor"],
                use_ocr=cfg["use_ocr"],
                use_validation=cfg["use_validation"],
                use_vision_fallback=cfg["use_vision_fallback"],
                use_hybrid_routing=cfg["use_hybrid_routing"],
            )
            ev = evaluate_prediction(c, pred)
            scores.append(ev)

        n = len(scores)
        avg_header_em = sum(s["header_exact_match"] for s in scores) / n
        avg_lines_f1 = sum(s["lines_f1"] for s in scores) / n
        avg_table_f1 = sum(s.get("table_f1", s["lines_f1"]) for s in scores) / n
        avg_arith_valid = sum(s.get("arithmetic_validity_rate", 1.0) for s in scores) / n
        avg_anomaly_f1 = sum(s["anomaly_f1"] for s in scores) / n
        avg_latency = sum(s["latency_ms"] for s in scores) / n
        avg_cost_doc = sum(s["cost_usd"] for s in scores) / n
        cost_per_1k = avg_cost_doc * 1000

        report["ablations"][a_id] = {
            "description": cfg["desc"],
            "header_exact_match": round(avg_header_em, 4),
            "lines_f1": round(avg_lines_f1, 4),
            "table_f1": round(avg_table_f1, 4),
            "arithmetic_validity_rate": round(avg_arith_valid, 4),
            "anomaly_f1": round(avg_anomaly_f1, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "cost_per_1000_invoices_usd": round(cost_per_1k, 3),
        }

        summary_rows.append(
            {
                "Condition": a_id,
                "Description": cfg["desc"],
                "Header EM (%)": f"{avg_header_em * 100:.1f}%",
                "Table F1 (%)": f"{avg_table_f1 * 100:.1f}%",
                "Arith Valid (%)": f"{avg_arith_valid * 100:.1f}%",
                "Anomaly F1 (%)": f"{avg_anomaly_f1 * 100:.1f}%",
                "Avg Latency (ms)": f"{avg_latency:.1f}",
            }
        )

    report_file = results_dir / "ablation_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    csv_file = results_dir / "ablation_summary.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    return report


def main() -> None:
    print("=" * 75)
    print(" InvoiceFlow AI - Architectural Ablation Studies Execution")
    print("=" * 75)
    report = asyncio.run(run_ablation_suite())

    print(f"\nAblations evaluated on {report['total_cases']} real document fixtures.")
    print("-" * 75)
    print(
        f"{'Condition':<23} | {'Header EM':<10} | {'Table F1':<10} | {'Arith Valid':<11} | {'Latency':<10}"
    )
    print("-" * 75)
    for a_id, stats in report["ablations"].items():
        em = f"{stats['header_exact_match'] * 100:.1f}%"
        tf1 = f"{stats['table_f1'] * 100:.1f}%"
        ar = f"{stats['arithmetic_validity_rate'] * 100:.1f}%"
        lat = f"{stats['avg_latency_ms']:.1f}ms"
        print(f"{a_id:<23} | {em:<10} | {tf1:<10} | {ar:<11} | {lat:<10}")
    print("-" * 75)
    print("Results saved to benchmarks/results/ablation_report.json")


if __name__ == "__main__":
    main()
