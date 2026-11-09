from typing import Any, List
from invoiceflow.domain.documents.models import CanonicalDocument
from invoiceflow.domain.invoices.models import FieldEvidence


class EvidenceMapper:
    def map_evidence(
        self,
        extracted_fields: dict[str, Any],
        canonical_doc: CanonicalDocument,
    ) -> List[FieldEvidence]:
        evidence_list: List[FieldEvidence] = []

        for field_path, val in extracted_fields.items():
            if val is None:
                continue

            str_val = str(val).strip()
            matched_el = None

            # 1. Exact or partial match search across document elements
            for el in canonical_doc.elements:
                if str_val in el.text or (len(str_val) >= 4 and str_val.lower() in el.text.lower()):
                    matched_el = el
                    break

            # 2. Search across structured table cells if not found in textual elements
            if not matched_el:
                for table in canonical_doc.tables:
                    for cell in table.cells:
                        if str_val in cell.text or (
                            len(str_val) >= 4 and str_val.lower() in cell.text.lower()
                        ):
                            matched_el = cell
                            break
                    if matched_el:
                        break

            if matched_el:
                page_idx = getattr(matched_el, "page_index", None)
                if page_idx is None and getattr(matched_el, "bbox", None) is not None:
                    page_idx = matched_el.bbox.page_index

                evidence_list.append(
                    FieldEvidence(
                        field_path=field_path,
                        source_kind=canonical_doc.source_format,
                        page_index=page_idx,
                        bbox=matched_el.bbox,
                        raw_value=matched_el.text,
                        normalized_value=str_val,
                        confidence=1.0,
                        extractor=canonical_doc.parser_name,
                    )
                )
            else:
                evidence_list.append(
                    FieldEvidence(
                        field_path=field_path,
                        source_kind=canonical_doc.source_format,
                        page_index=None,
                        bbox=None,
                        raw_value=None,
                        normalized_value=str_val,
                        confidence=None,
                        extractor=canonical_doc.parser_name,
                        review_reason="no_direct_text_match",
                    )
                )

        return evidence_list
