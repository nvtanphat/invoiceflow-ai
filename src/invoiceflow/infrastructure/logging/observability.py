import logging
import re
from typing import Any, Dict, Optional

_SENSITIVE_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE), "Bearer ***REDACTED***"),
    (
        re.compile(
            r"""(?i)(["']?(?:password|token|secret|api[_-]?key)["']?\s*[:=]\s*["']?)([^"'&\s,]+)(["']?)"""
        ),
        r"\1***REDACTED***\3",
    ),
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE), "sk-***REDACTED***"),
    (
        re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
        "****-****-****-****",
    ),
]


class PIIRedactingFilter(logging.Filter):
    """Logging filter that automatically redacts sensitive authentication credentials,

    API keys, passwords, and PII from all log output records before emission.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (self.redact(v) if isinstance(v, str) else v) for k, v in record.args.items()
                }
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    (self.redact(arg) if isinstance(arg, str) else arg) for arg in record.args
                )
        return True

    @classmethod
    def redact(cls, text: str) -> str:
        for pattern, replacement in _SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


def build_structured_log_payload(
    stage: str,
    tenant_id: str,
    document_id: Optional[str] = None,
    job_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    cost_usd: Optional[float] = None,
    error_code: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Constructs a telemetry-compliant JSON-serializable structured log payload."""
    payload: Dict[str, Any] = {
        "stage": stage,
        "tenant_id": str(tenant_id),
    }
    if document_id:
        payload["document_id"] = str(document_id)
    if job_id:
        payload["job_id"] = str(job_id)
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 2)
    if cost_usd is not None:
        payload["cost_usd"] = round(cost_usd, 4)
    if error_code:
        payload["error_code"] = error_code
    if extra:
        payload.update(extra)
    return payload
