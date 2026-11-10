from invoiceflow.domain.invoices.evidence_gate import review_items
from invoiceflow.domain.invoices.models import FieldEvidence, FieldVerificationState


def _ev(path, state, source="pdf", value=None):
    return FieldEvidence(
        field_path=path, source_kind=source, verification_state=state, normalized_value=value
    )


def test_review_items_list_only_fields_needing_a_human_with_their_candidates():
    records = [
        _ev("supplier_tax_id", FieldVerificationState.VALID, value="0100109106"),
        _ev("subtotal", FieldVerificationState.CONFLICT, value="6000000"),
        _ev("subtotal.candidate_vision", "model_proposed", source="vision_llm", value="60000000"),
        _ev("amount_payable", FieldVerificationState.MODEL_PROPOSED, "vision_llm", "66000000"),
        _ev("tax_total", FieldVerificationState.HUMAN_APPROVED, value="6000000"),
        _ev("issue_date.candidate_vision", "human_rejected", source="vision_llm", value="x"),
    ]

    items = {item.field_path: item for item in review_items(records, line_count=0)}

    assert set(items) >= {"subtotal", "amount_payable"}
    assert "supplier_tax_id" not in items
    assert "tax_total" not in items
    # A rejected candidate is settled; only the missing primary evidence remains.
    assert items["issue_date"].candidate_value is None
    assert items["issue_date"].reasons == ["MISSING_FIELD_EVIDENCE"]
    assert items["subtotal"].current_value == "6000000"
    assert items["subtotal"].candidate_value == "60000000"
    assert items["amount_payable"].source_kind == "vision_llm"
    # Critical fields without any evidence are listed too, so nothing is silently skipped.
    assert "invoice_number" in items
    assert items["invoice_number"].reasons == ["MISSING_FIELD_EVIDENCE"]


def test_human_rejected_candidates_do_not_block_automation_or_review():
    records = [
        _ev("issue_date", FieldVerificationState.HUMAN_APPROVED, value="2026-03-20"),
        _ev("issue_date.candidate_vision", "human_rejected", source="vision_llm"),
    ]

    assert "issue_date" not in {item.field_path for item in review_items(records, 0)}
