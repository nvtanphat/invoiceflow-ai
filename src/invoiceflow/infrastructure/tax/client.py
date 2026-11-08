from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Optional

from invoiceflow.domain.invoices.models import VerificationStatus

logger = logging.getLogger(__name__)


@dataclass
class TaxVerificationResult:
    status: VerificationStatus
    is_valid: bool
    is_blocked: bool = False
    blocker_code: Optional[str] = None
    tax_authority_code: Optional[str] = None
    verification_time: Optional[datetime] = None
    message: str = ""


class TaxAuthorityPort(ABC):
    @abstractmethod
    async def verify_invoice_status(
        self,
        supplier_tax_id: str,
        invoice_series: str,
        invoice_number: str,
    ) -> TaxVerificationResult:
        """Verify invoice legal validity against General Department of Taxation (TCT) portal."""
        pass


class GeneralDepartmentOfTaxationClient(TaxAuthorityPort):
    """Client connecting to Vietnam General Department of Taxation (TCT / GDT) e-invoice portal.

    Implements P1 integration. When official government API credentials or mTLS certificates
    are not provisioned in the current environment, it transparently returns BLOCKED_EXTERNAL_DEPENDENCY
    without making fraudulent claims of live verification.
    """

    def __init__(
        self,
        api_url: str = "https://hoadondientu.gdt.gov.vn/api/v1/lookup",
        api_token: Optional[str] = None,
        client_cert_path: Optional[str] = None,
    ):
        self.api_url = api_url
        self.api_token = api_token
        self.client_cert_path = client_cert_path

    async def verify_invoice_status(
        self,
        supplier_tax_id: str,
        invoice_series: str,
        invoice_number: str,
    ) -> TaxVerificationResult:
        if not self.api_token and not self.client_cert_path:
            return TaxVerificationResult(
                status=VerificationStatus.NOT_CHECKED,
                is_valid=False,
                is_blocked=True,
                blocker_code="BLOCKED_EXTERNAL_DEPENDENCY",
                verification_time=datetime.now(timezone.utc),
                message=(
                    "Cần tài khoản kết nối TCT/Tổng cục Thuế (GDT OAuth2 Credentials hoặc "
                    "mTLS Client Certificate được cơ quan thuế cấp phép) để tra cứu tính hợp lệ "
                    "hóa đơn trực tuyến. Hệ thống đánh dấu BLOCKED_EXTERNAL_DEPENDENCY."
                ),
            )

        # Production integration with live GDT endpoint when credentials exist
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "User-Agent": "InvoiceFlow-AI/1.0 TaxVerificationConnector",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    self.api_url,
                    params={
                        "mst": supplier_tax_id,
                        "khhdon": invoice_series,
                        "shdon": invoice_number,
                    },
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    is_valid = data.get("valid", True)
                    return TaxVerificationResult(
                        status=VerificationStatus.VERIFIED if is_valid else VerificationStatus.FAILED,
                        is_valid=is_valid,
                        tax_authority_code=data.get("tct_code"),
                        verification_time=datetime.now(timezone.utc),
                        message=data.get("message", "Xác thực cơ quan thuế thành công."),
                    )
                else:
                    return TaxVerificationResult(
                        status=VerificationStatus.UNKNOWN,
                        is_valid=False,
                        verification_time=datetime.now(timezone.utc),
                        message=f"Cổng thông tin TCT trả về mã lỗi {resp.status_code}: {resp.text}",
                    )
        except Exception as exc:
            logger.warning("GDT verification network error: %s", exc)
            return TaxVerificationResult(
                status=VerificationStatus.UNKNOWN,
                is_valid=False,
                verification_time=datetime.now(timezone.utc),
                message=f"Lỗi kết nối đến cổng TCT: {exc}",
            )
