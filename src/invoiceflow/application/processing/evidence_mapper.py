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

            if matched_el:
                evidence_list.append(
                    FieldEvidence(
                        field_path=field_path,
                        source_kind=canonical_doc.source_format,
                        page_index=matched_el.page_index,
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
