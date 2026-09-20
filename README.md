# sendflit — Python

Transactional email for applications and AI agents. Zero dependencies (stdlib only), Python 3.9+.

## Install

```bash
pip install sendflit
```

## Usage

```python
from sendflit import SendFlit

sf = SendFlit(api_key="re_...")  # or: SendFlit("re_...")

res = sf.send(
    from_="you@yourdomain.com",
    to="user@example.com",
    subject="Confirm your email",
    html="<p>Click <a href='...'>here</a> to confirm.</p>",
)
print(res["id"], res["status"])
```

### Attachments

```python
sf.send(
    from_="billing@yourdomain.com",
    to="user@example.com",
    subject="Your receipt",
    html="<p>Thanks!</p>",
    attachments=[{"filename": "receipt.pdf", "content": pdf_bytes}],
)
```

### Batch (up to 100)

```python
res = sf.batch([
    {"from": "you@yourdomain.com", "to": "a@example.com", "subject": "Hi A", "html": "<p>A</p>"},
    {"from": "you@yourdomain.com", "to": "b@example.com", "subject": "Hi B", "html": "<p>B</p>"},
])
```

### Templates

```python
sf.send(
    from_="you@yourdomain.com",
    to="user@example.com",
    template_id="tmpl_...",
    variables={"name": "Mehedi"},
)
```

### Safe retries (idempotency)

```python
# Retrying with the same key replays the original result instead of
# risking a duplicate send — safe to call again after a timeout.
sf.send(
    from_="you@yourdomain.com",
    to="user@example.com",
    subject="Order confirmed",
    html="<p>…</p>",
    idempotency_key=f"order-{order_id}",
)

sf.batch(emails, idempotency_key=f"digest-{today}")
```

### Webhook verification (Flask example)

```python
from sendflit import verify_webhook_signature

@app.post("/webhooks/sendflit")
def hook():
    raw = request.get_data()
    sig = request.headers.get("X-Sendflit-Signature", "")
    if not verify_webhook_signature(WEBHOOK_SECRET, raw, sig):
        return {"error": "invalid signature"}, 401
    event = json.loads(raw)
    if event["type"] == "email.bounced":
        ...
    return "", 200
```

## API

### `SendFlit(api_key, base_url="https://api.sendflit.com", timeout=15, max_retries=2)`

Retries 429/5xx with backoff; honors `Retry-After`. Errors raise `SendFlitError` with `.status` / `.body`.

### Methods

| Method | Endpoint |
|---|---|
| `send(**email, idempotency_key=None)` | `POST /v1/email` |
| `batch(emails, idempotency_key=None)` | `POST /v1/emails/batch` |
| `list_emails(limit, offset, status)` | `GET /v1/emails` |
| `get_email(id)` / `cancel_email(id)` | `GET/DELETE /v1/emails/{id}` |
| `add_domain(name)` / `list_domains()` / `verify_domain(id)` | `/v1/domains…` |
| `create_template(name, subject, html, text)` | `POST /v1/templates` |
| `add_contact(email, …)` / `list_contacts(…)` | `/v1/contacts…` |
| `suppress(email, reason)` | `POST /v1/suppressions` |
| `usage()` / `health()` | `/v1/usage`, `/health` |

MIT © SendFlit
