# DataFlow AI — Technical Documentation
**API Reference & Developer Guide | v3.2**

---

## Authentication

### API Key Authentication
All DataFlow API requests require authentication via an API key passed in the `Authorization` header.

```http
Authorization: Bearer df_live_xxxxxxxxxxxxxxxxxxxx
```

API keys are created in the DataFlow dashboard under **Settings → API Keys**. Each key can be scoped to specific permissions: `read`, `write`, `admin`.

**Key types:**
- `df_live_` prefix — production environment
- `df_test_` prefix — sandbox environment (no billing, rate-limited)

**Error codes for authentication failures:**
- `401 Unauthorized` — missing or malformed Authorization header
- `403 Forbidden` — valid key but insufficient permissions for the requested operation
- `429 Too Many Requests` — rate limit exceeded (see Rate Limits section)

### OAuth 2.0 (Enterprise)
Enterprise customers can authenticate via OAuth 2.0 using the authorization code flow. The token endpoint is `https://auth.dataflow.ai/oauth/token`.

```bash
curl -X POST https://auth.dataflow.ai/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "grant_type": "authorization_code",
    "client_id": "your_client_id",
    "client_secret": "your_client_secret",
    "code": "authorization_code",
    "redirect_uri": "https://yourapp.com/callback"
  }'
```

Access tokens expire after **3600 seconds**. Use the `refresh_token` to obtain new access tokens without re-authentication.

---

## Rate Limits

API rate limits are enforced per API key, per minute.

| Plan | Requests/minute | Burst | Events/second |
|------|----------------|-------|---------------|
| Starter | 100 | 200 | 1,000 |
| Growth | 500 | 1,000 | 10,000 |
| Enterprise | 2,000 | 5,000 | 100,000 |

**Rate limit headers returned with every response:**
```http
X-RateLimit-Limit: 500
X-RateLimit-Remaining: 487
X-RateLimit-Reset: 1704067260
```

When you exceed the rate limit, the API returns `429 Too Many Requests` with a `Retry-After` header indicating seconds to wait.

**Best practices:**
- Implement exponential backoff with jitter starting at 1 second
- Cache responses where data freshness allows
- Use bulk endpoints (`/events/batch`) for high-volume ingestion
- Monitor `X-RateLimit-Remaining` and throttle proactively

---

## Events API

### Ingesting Events
Send raw events to DataFlow for real-time processing.

**Endpoint:** `POST /v3/events`

```json
{
  "stream": "orders",
  "events": [
    {
      "event_id": "evt_8f3k2j",
      "timestamp": "2025-01-15T14:32:00Z",
      "type": "order.placed",
      "user_id": "usr_9a1b2c",
      "properties": {
        "order_value": 149.99,
        "currency": "USD",
        "product_ids": ["prod_001", "prod_043"],
        "channel": "mobile_app"
      }
    }
  ]
}
```

**Response:**
```json
{
  "accepted": 1,
  "rejected": 0,
  "stream": "orders",
  "latency_ms": 12
}
```

### Batch Ingestion
For high-volume scenarios, use the batch endpoint which accepts up to **1,000 events per request**.

**Endpoint:** `POST /v3/events/batch`

Events are processed asynchronously. Use the returned `batch_id` to check processing status via `GET /v3/batches/{batch_id}`.

### Filtering Events by Date Range
Use query parameters to filter events when querying historical data.

```http
GET /v3/events?stream=orders&from=2025-01-01T00:00:00Z&to=2025-01-31T23:59:59Z&limit=100
```

**Query parameters:**
- `stream` (required) — event stream name
- `from` — ISO 8601 start datetime (inclusive)
- `to` — ISO 8601 end datetime (inclusive)
- `limit` — results per page (max: 1000, default: 100)
- `cursor` — pagination cursor from previous response
- `filter` — JSON-encoded property filter (e.g. `{"type":"order.placed"}`)

---

## Webhook Configuration

### Setting Up Webhooks
DataFlow sends real-time HTTP POST callbacks to your endpoint when specified events occur.

**Create a webhook:**

```http
POST /v3/webhooks
Content-Type: application/json
Authorization: Bearer df_live_xxx

{
  "name": "Order Events Webhook",
  "url": "https://yourapp.com/webhooks/dataflow",
  "events": ["order.placed", "order.cancelled", "order.refunded"],
  "secret": "your_signing_secret_here",
  "active": true
}
```

**Response:**
```json
{
  "webhook_id": "wh_1a2b3c4d",
  "name": "Order Events Webhook",
  "url": "https://yourapp.com/webhooks/dataflow",
  "events": ["order.placed", "order.cancelled", "order.refunded"],
  "active": true,
  "created_at": "2025-01-15T14:00:00Z"
}
```

### Verifying Webhook Signatures
Every webhook payload is signed using HMAC-SHA256. Verify signatures to prevent spoofing.

```python
import hmac
import hashlib

def verify_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(
        key=secret.encode(),
        msg=payload_body,
        digestmod=hashlib.sha256
    ).hexdigest()
    received = signature_header.replace("sha256=", "")
    return hmac.compare_digest(expected, received)
```

The signature is passed in the `X-DataFlow-Signature` header with each webhook delivery.

### Webhook Retry Policy
Failed deliveries (non-2xx response or timeout >30s) are retried with exponential backoff:
- Retry 1: 5 minutes
- Retry 2: 30 minutes
- Retry 3: 2 hours
- Retry 4: 8 hours
- Retry 5: 24 hours (final attempt)

After 5 failed attempts, the webhook is automatically deactivated and an email notification is sent to the account owner.

---

## Python SDK

### Installation
```bash
pip install dataflow-ai
```

### Quickstart
```python
from dataflow import DataFlowClient

client = DataFlowClient(api_key="df_live_xxx")

# Send an event
client.events.track(
    stream="orders",
    event_type="order.placed",
    user_id="usr_123",
    properties={"order_value": 99.99, "currency": "USD"}
)

# Query a metric
result = client.metrics.get(
    metric="order.placed.count",
    from_date="2025-01-01",
    to_date="2025-01-31",
    group_by="channel"
)
print(result.data)
```

### SDK Installation on ARM64 (Apple Silicon)
The SDK supports Python 3.9+ on macOS ARM64 (M1/M2/M3/M4/M5). Install with native ARM wheels:
```bash
pip install dataflow-ai --prefer-binary
```

For on-premise or airgapped environments, download the wheel from the customer portal and install:
```bash
pip install dataflow_ai-3.2.0-py3-none-any.whl
```

---

## Dashboard API

### Creating Dashboards Programmatically
```http
POST /v3/dashboards
Content-Type: application/json

{
  "name": "Sales Performance",
  "description": "Real-time sales metrics by region",
  "template": "retail_sales",
  "visibility": "team",
  "widgets": [
    {
      "type": "metric",
      "title": "Today's Revenue",
      "query": {
        "metric": "order.revenue.sum",
        "period": "today"
      }
    },
    {
      "type": "timeseries",
      "title": "Orders per Hour",
      "query": {
        "metric": "order.placed.count",
        "period": "last_7_days",
        "granularity": "hour"
      }
    }
  ]
}
```

### Embedding Dashboards
Embed any dashboard into your application using the embed URL.

```javascript
const embedToken = await client.dashboards.createEmbedToken({
  dashboard_id: "dash_abc123",
  user_id: "external_user_001",
  expires_in: 3600,
  theme: "dark"
});

// Embed in an iframe
const url = `https://embed.dataflow.ai/d/${embedToken}`;
```

---

## Data Connectors

### Connecting Snowflake
```python
client.connectors.create({
    "type": "snowflake",
    "name": "Production DWH",
    "config": {
        "account": "xy12345.us-east-1",
        "warehouse": "COMPUTE_WH",
        "database": "ANALYTICS",
        "schema": "PUBLIC",
        "username": "dataflow_svc",
        "private_key_path": "/keys/snowflake_key.p8"
    },
    "sync_schedule": "*/15 * * * *"  # every 15 minutes
})
```

### Connecting Kafka (Real-Time Streaming)
```yaml
# connector-config.yml
connector:
  type: kafka
  name: production_events
  bootstrap_servers: kafka.internal:9092
  topic: user_events
  consumer_group: dataflow_consumer
  auto_offset_reset: latest
  schema_registry: http://schema-registry:8081
  format: avro
```

---

## Error Reference

| Code | HTTP Status | Description | Resolution |
|------|------------|-------------|------------|
| `auth_missing` | 401 | Authorization header absent | Add `Authorization: Bearer <key>` |
| `auth_invalid` | 401 | API key malformed or revoked | Regenerate key in dashboard |
| `auth_forbidden` | 403 | Insufficient key permissions | Update key scopes |
| `rate_limited` | 429 | Rate limit exceeded | Wait for `Retry-After` seconds |
| `stream_not_found` | 404 | Stream doesn't exist | Create stream first |
| `payload_too_large` | 413 | Request body > 10MB | Split into smaller batches |
| `schema_violation` | 422 | Event properties don't match schema | Check schema in dashboard |
| `server_error` | 500 | Internal DataFlow error | Check status.dataflow.ai |

---

## Data Retention & Compliance

**Default retention periods:**
- Raw events: 90 days (Starter/Growth), unlimited (Enterprise)
- Aggregated metrics: 2 years (all plans)
- Dashboard snapshots: 30 days (all plans)

**GDPR compliance:**
- User data deletion: `DELETE /v3/users/{user_id}` — purges within 72 hours
- Data export: `GET /v3/users/{user_id}/export` — returns all stored data as JSON
- Processing agreement: available in the customer portal under Legal → DPA

**SOC 2 Type II:** Annual audit, most recent report available upon NDA request.

---

## Troubleshooting

### Common Issues

**"Connection timeout" on event ingestion**
- Check your network allows outbound HTTPS to `api.dataflow.ai` (port 443)
- Verify DNS resolution: `nslookup api.dataflow.ai`
- Use the SDK's built-in retry logic: `client = DataFlowClient(retry=3)`

**Events are ingested but not appearing in dashboards**
- Verify the event `stream` name matches the dashboard query
- Check event timestamp — events with future timestamps are held until that time
- Dashboard cache refreshes every 5 seconds; wait and hard-refresh (Ctrl+Shift+R)

**Webhook deliveries are failing with 503**
- Your endpoint must respond within **30 seconds**
- For long processing, respond 200 immediately and process async
- Check webhook delivery logs in **Dashboard → Webhooks → Deliveries**

**SDK ImportError on macOS ARM64**
- Ensure Python 3.9+ is installed via Homebrew (not system Python)
- Try: `pip install dataflow-ai --upgrade --force-reinstall`
- If using Conda: `conda install -c conda-forge dataflow-ai`
