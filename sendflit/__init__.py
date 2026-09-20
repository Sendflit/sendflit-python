"""SendFlit Python SDK — zero-dependency (stdlib urllib), Python 3.9+.

Transactional email API for applications and AI agents.
"""
from __future__ import annotations

import hmac as _hmac
import json as _json
import time as _time
import urllib.error as _urlerr
import urllib.request as _urlreq
from typing import Any, BinaryIO, Iterable, Mapping, Optional, Sequence, Union

__version__ = "1.1.0"
DEFAULT_BASE = "https://api.sendflit.com"

__all__ = ["SendFlit", "SendFlitError", "verify_webhook_signature", "__version__"]


class SendFlitError(Exception):
    def __init__(self, message: str, status: int = 0, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class SendFlit:
    """Client for the SendFlit API.

    Args:
        api_key: API key (starts with ``re_``).
        base_url: API root; default https://api.sendflit.com
        timeout: per-request timeout seconds (default 15).
        max_retries: retries for 429/5xx (default 2, respects Retry-After).
    """

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE,
                 timeout: float = 15.0, max_retries: int = 2) -> None:
        if not api_key:
            raise TypeError("SendFlit: api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------- transport

    def _request(self, method: str, path: str, body: Optional[Mapping] = None,
                 idempotency_key: Optional[str] = None) -> dict:
        url = f"{self.base_url}/v1{path}"
        data = _json.dumps(body).encode() if body is not None else None
        attempt = 0
        while True:
            req = _urlreq.Request(url, data=data, method=method)
            req.add_header("Authorization", f"Bearer {self.api_key}")
            req.add_header("User-Agent", f"sendflit-python/{__version__}")
            if data is not None:
                req.add_header("Content-Type", "application/json")
            if idempotency_key:
                req.add_header("Idempotency-Key", idempotency_key)
            try:
                with _urlreq.urlopen(req, timeout=self.timeout) as r:
                    return _json.loads(r.read().decode() or "{}")
            except _urlerr.HTTPError as e:
                retry_after = e.headers.get("retry-after") if e.headers else None
                text = ""
                try:
                    text = e.read().decode()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    parsed = _json.loads(text) if text else {}
                except Exception:  # noqa: BLE001
                    parsed = {"raw": text}
                retryable = e.code == 429 or e.code >= 500
                if retryable and attempt < self.max_retries:
                    attempt += 1
                    delay = float(retry_after) if retry_after else 0.3 * 2 ** attempt
                    _time.sleep(delay)
                    continue
                detail = parsed.get("detail")
                if isinstance(detail, str):
                    msg = detail
                elif isinstance(detail, list):
                    msg = "; ".join(d.get("msg", str(d)) for d in detail)
                else:
                    msg = f"SendFlit API error ({e.code})"
                raise SendFlitError(msg, e.code, parsed) from None
            except _urlerr.URLError as e:
                raise SendFlitError(f"Network error: {e.reason}", 0, None) from None

    # ----------------------------------------------------------------- email

    def send(
        self,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        html: Optional[str] = None,
        text: Optional[str] = None,
        cc: Optional[Sequence[str]] = None,
        bcc: Optional[Sequence[str]] = None,
        reply_to: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        template_id: Optional[str] = None,
        template_name: Optional[str] = None,
        variables: Optional[Mapping[str, str]] = None,
        attachments: Optional[Sequence[Mapping[str, Any]]] = None,
        scheduled_at: Optional[str] = None,
        to_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        **extra: Any,
    ) -> dict:
        """Send a transactional email.

        ``attachments`` items: ``{"filename": str, "content": str|bytes,
        "content_type": str}`` — content is base64-encoded for you.

        ``idempotency_key``: safe retries — resending the exact same request
        with the same key replays the original result (success or failure)
        instead of risking a duplicate send. Reusing the key with a
        different request body is rejected with a 409.
        """
        payload: dict[str, Any] = {k: v for k, v in {
            "from": from_, "to": to, "to_name": to_name, "subject": subject,
            "html": html, "text": text, "cc": list(cc) if cc else None,
            "bcc": list(bcc) if bcc else None, "reply_to": reply_to,
            "headers": dict(headers) if headers else None,
            "template_id": template_id, "template_name": template_name,
            "variables": dict(variables) if variables else None,
            "scheduled_at": scheduled_at,
            "attachments": [self._att(a) for a in attachments] if attachments else None,
        }.items() if v is not None}
        payload.update(extra)
        return self._request("POST", "/email", payload, idempotency_key=idempotency_key)

    def batch(self, emails: Sequence[Mapping[str, Any]],
             idempotency_key: Optional[str] = None) -> dict:
        """Send up to 100 emails in one call. ``idempotency_key`` covers the
        whole batch — see ``send()``."""
        if not emails:
            raise TypeError("batch() expects a non-empty list")
        if len(emails) > 100:
            raise ValueError("batch() accepts at most 100 emails per call")
        norm = []
        for e in emails:
            e = dict(e)
            if "attachments" in e and e["attachments"]:
                e["attachments"] = [self._att(a) for a in e["attachments"]]
            norm.append(e)
        return self._request("POST", "/emails/batch", {"emails": norm}, idempotency_key=idempotency_key)

    @staticmethod
    def _att(a: Mapping[str, Any]) -> dict:
        import base64 as _b64
        content = a["content"]
        raw = content.encode() if isinstance(content, str) else bytes(content)
        return {"filename": a["filename"],
                "content_b64": _b64.b64encode(raw).decode(),
                "content_type": a.get("content_type", "application/octet-stream")}

    # ----------------------------------------------------------------- reads

    def list_emails(self, limit: Optional[int] = None, offset: Optional[int] = None,
                    status: Optional[str] = None) -> dict:
        q = {k: v for k, v in {"limit": limit, "offset": offset, "status": status}.items() if v is not None}
        from urllib.parse import urlencode
        return self._request("GET", "/emails" + ("?" + urlencode(q) if q else ""))

    def get_email(self, email_id: str) -> dict:
        return self._request("GET", f"/emails/{email_id}")

    def cancel_email(self, email_id: str) -> dict:
        return self._request("DELETE", f"/emails/{email_id}")

    # --------------------------------------------------------------- domains

    def add_domain(self, name: str) -> dict:
        return self._request("POST", "/domains", {"name": name})

    def list_domains(self) -> dict:
        return self._request("GET", "/domains")

    def verify_domain(self, domain_id: str) -> dict:
        return self._request("POST", f"/domains/{domain_id}/verify")

    # ------------------------------------------------------------- templates

    def create_template(self, name: str, subject: str, html: str = "",
                        text: str = "") -> dict:
        return self._request("POST", "/templates",
                             {"name": name, "subject": subject, "html": html, "text": text})

    def list_templates(self) -> dict:
        return self._request("GET", "/templates")

    # -------------------------------------------------------------- contacts

    def add_contact(self, email: str, name: str = "", audience: str = "default",
                    data: Optional[Mapping[str, Any]] = None) -> dict:
        return self._request("POST", "/contacts",
                             {"email": email, "name": name, "audience": audience,
                              **({"data": dict(data)} if data else {})})

    def list_contacts(self, limit: Optional[int] = None, offset: Optional[int] = None,
                      audience: Optional[str] = None) -> dict:
        q = {k: v for k, v in {"limit": limit, "offset": offset, "audience": audience}.items() if v is not None}
        from urllib.parse import urlencode
        return self._request("GET", "/contacts" + ("?" + urlencode(q) if q else ""))

    # ------------------------------------------------------------------ misc

    def suppress(self, email: str, reason: str = "unsubscribe") -> dict:
        return self._request("POST", "/suppressions", {"email": email, "reason": reason})

    def usage(self) -> dict:
        return self._request("GET", "/usage")

    def health(self) -> dict:
        """Liveness probe (root-level, not under /v1)."""
        req = _urlreq.Request(f"{self.base_url}/health")
        req.add_header("User-Agent", f"sendflit-python/{__version__}")
        with _urlreq.urlopen(req, timeout=self.timeout) as r:
            return _json.loads(r.read().decode() or "{}")


def verify_webhook_signature(secret: str, raw_body: Union[bytes, str],
                             signature: str) -> bool:
    """Verify an ``X-Sendflit-Signature`` header value against the raw body."""
    if isinstance(raw_body, str):
        raw_body = raw_body.encode()
    expected = "sha256=" + _hmac.new(secret.encode(), raw_body, "sha256").hexdigest()
    return _hmac.compare_digest(expected, str(signature or ""))
