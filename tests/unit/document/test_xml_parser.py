import pytest
from decimal import Decimal


SAMPLE_VN_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<HDon>
  <DLHDon>
    <TTChung>
      <KHMSHDon>1</KHMSHDon>
      <KHHDon>1C26TAA</KHHDon>
      <SHDon>0000042</SHDon>
      <NLap>2026-11-08</NLap>
      <DVTTe>VND</DVTTe>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>C\xc3\xb4ng ty C\xe1\xbb\x95 ph\xe1\xba\xa7n M\xe1\xba\xabu Vi\xe1\xbb\x87t</Ten>
        <MST>0109876543</MST>
        <DChi>H\xc3\xa0 N\xe1\xbb\x99i, Vi\xe1\xbb\x87t Nam</DChi>
      </NBan>
      <NMua>
        <Ten>C\xc3\xb4ng ty TNHH Kh\xc3\xa1ch H\xc3\xa0ng</Ten>
        <MST>0301234567</MST>
      </NMua>
      <DSHHDVu>
        <HHDVu>
          <STT>1</STT>
          <THHDVu>D\xe1\xbb\x8bch v\xe1\xbb\xa5 ph\xe1\xba\xa7n m\xe1\xbb\x81m InvoiceFlow</THHDVu>
          <DVTinh>G\xc3\xb3i</DVTinh>
          <SLuong>1.0000</SLuong>
          <DGia>10000000.0000</DGia>
          <TLCKhau>0.00</TLCKhau>
          <STCKhau>0.0000</STCKhau>
          <TSuat>10%</TSuat>
          <ThTien>10000000.0000</ThTien>
        </HHDVu>
      </DSHHDVu>
      <TToan>
        <TgTCThue>10000000.0000</TgTCThue>
        <TgTThue>1000000.0000</TgTThue>
        <TgTTTBSo>11000000.0000</TgTTTBSo>
      </TToan>
    </NDHDon>
  </DLHDon>
  <DSCKS>
    <NBan>
      <Signature>SignedDataSample</Signature>
    </NBan>
  </DSCKS>
</HDon>
"""

MALICIOUS_XXE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
  <!ELEMENT foo ANY >
  <!ENTITY xxe SYSTEM "file:///etc/passwd" >]>
<HDon>
  <DLHDon>
    <TTChung><SHDon>&xxe;</SHDon></TTChung>
  </DLHDon>
</HDon>
"""


def test_secure_xml_parser_parses_vn_invoice():
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
    import uuid

    parser = SecureXMLParser()
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    inv = parser.parse_invoice_xml(
        tenant_id=tenant_id,
        document_id=doc_id,
        xml_content=SAMPLE_VN_XML,
    )
    assert inv.supplier_tax_id == "0109876543"
    assert inv.invoice_number == "0000042"
    assert inv.invoice_series == "1C26TAA"
    assert inv.amount_payable == Decimal("11000000.0000")
    assert len(inv.lines) == 1
    assert inv.lines[0].line_amount == Decimal("10000000.0000")
    assert inv.signature_status.value in ("unverified", "unknown", "not_checked")


def test_secure_xml_parser_rejects_xxe_payload():
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser, XMLParsingError
    import uuid

    parser = SecureXMLParser()
    with pytest.raises(XMLParsingError):
        parser.parse_invoice_xml(
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            xml_content=MALICIOUS_XXE_XML,
        )


def test_secure_xml_parser_emits_source_evidence_for_every_parsed_field():
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser

    inv = SecureXMLParser().parse_invoice_xml(
        "00000000-0000-0000-0000-0000000000aa",
        "00000000-0000-0000-0000-000000000001",
        SAMPLE_VN_XML,
    )
    evidence = {ev.field_path: ev for ev in inv.evidence}

    for path in (
        "supplier_tax_id",
        "supplier_name",
        "invoice_number",
        "invoice_series",
        "issue_date",
        "subtotal",
        "tax_total",
        "amount_payable",
        "lines[0].qty",
        "lines[0].unit_price",
        "lines[0].line_amount",
    ):
        assert path in evidence, path
        assert evidence[path].source_kind == "xml"
        assert evidence[path].extractor == "xml_deterministic"
        assert evidence[path].raw_value
    assert evidence["supplier_tax_id"].raw_value == "0109876543"
    assert evidence["lines[0].qty"].raw_value == "1.0000"


def test_secure_xml_parser_does_not_invent_missing_quantity_or_amount():
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser

    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?><HDon><DLHDon><TTChung><SHDon>0000077</SHDon>'
        b"</TTChung><NDHDon><DSHHDVu><HHDVu><STT>1</STT><THHDVu>Dich vu</THHDVu>"
        b"<DGia>500000</DGia></HHDVu></DSHHDVu></NDHDon></DLHDon></HDon>"
    )

    inv = SecureXMLParser().parse_invoice_xml(
        "00000000-0000-0000-0000-0000000000aa", "00000000-0000-0000-0000-000000000002", xml
    )
    paths = {ev.field_path for ev in inv.evidence}

    assert "lines[0].qty" not in paths
    assert "lines[0].line_amount" not in paths
    assert "QTY_MISSING_IN_SOURCE" in inv.lines[0].issues
    assert "LINE_AMOUNT_MISSING_IN_SOURCE" in inv.lines[0].issues
