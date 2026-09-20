"""Smoke tests for the SendFlit Python SDK (run against a local server)."""
import base64
import hmac
import http.server
import json
import threading

import pytest

from sendflit import SendFlit, SendFlitError, verify_webhook_signature

BASE = "http://127.0.0.1:9353"


def test_requires_key():
    with pytest.raises(TypeError):
        SendFlit("")


def test_health():
    sf = SendFlit("re_x", base_url=BASE, max_retries=0)
    h = sf.health()
    assert h  # any 200 json


def test_auth_error():
    sf = SendFlit("re_x", base_url=BASE, max_retries=0)
    with pytest.raises(SendFlitError) as ei:
        sf.list_emails()
    assert ei.value.status == 401


def test_batch_validation():
    sf = SendFlit("re_x", base_url=BASE, max_retries=0)
    with pytest.raises(TypeError):
        sf.batch([])
    with pytest.raises(ValueError):
        sf.batch([{}] * 101)


def test_attachment_encoding():
    a = SendFlit._att({"filename": "f.txt", "content": "hi"})
    assert a["content_b64"] == base64.b64encode(b"hi").decode()
    a2 = SendFlit._att({"filename": "f.bin", "content": b"\x00\x01"})
    assert base64.b64decode(a2["content_b64"]) == b"\x00\x01"


def test_webhook_signature():
    body = json.dumps({"type": "email.sent"}).encode()
    sig = "sha256=" + hmac.new(b"whsec_t", body, "sha256").hexdigest()
    assert verify_webhook_signature("whsec_t", body, sig)
    assert not verify_webhook_signature("whsec_t", body + b" ", sig)
    assert not verify_webhook_signature("whsec_t", body, "sha256=bad")


def test_payload_normalization_roundtrip():
    """send() builds the right JSON — checked via an echo server."""
    got = {}

    class Echo(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            got["body"] = json.loads(self.rfile.read(n))
            got["auth"] = self.headers.get("Authorization")
            got["idempotency_key"] = self.headers.get("Idempotency-Key")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"x","status":"sent"}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        sf = SendFlit("re_k", base_url=f"http://127.0.0.1:{srv.server_port}", max_retries=0)
        sf.send(from_="a@b.com", to="c@d.com", reply_to="r@b.com",
                template_id="t1", variables={"x": "1"},
                attachments=[{"filename": "f.txt", "content": "hi"}])
        first_body, first_auth = got["body"], got["auth"]
        assert got["idempotency_key"] is None

        sf.send(from_="a@b.com", to="c@d.com", idempotency_key="order-123")
        assert got["idempotency_key"] == "order-123"

        sf.batch([{"from": "a@b.com", "to": "c@d.com"}], idempotency_key="batch-1")
        assert got["idempotency_key"] == "batch-1"
    finally:
        srv.shutdown()
    assert first_auth == "Bearer re_k"
    assert first_body["reply_to"] == "r@b.com"
    assert first_body["template_id"] == "t1"
    assert first_body["attachments"][0]["content_b64"] == base64.b64encode(b"hi").decode()
    # None-valued optional fields must not serialize
    assert "cc" not in first_body and "bcc" not in first_body
