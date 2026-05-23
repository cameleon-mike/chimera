# Chimera — Database Schema Reference

SQLite database : `storage/risk_db.sqlite`

Migration strategy : all tables use `CREATE TABLE IF NOT EXISTS` — idempotent on restart.

---

## Tables

### `domain_probe`

Stores static probe results from `/probe/{domain}`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| domain | TEXT | FQDN probed |
| probed_at | TEXT | ISO 8601 UTC timestamp |
| risk_score | REAL | 0.0–1.0 static risk score |
| vendors_json | TEXT | JSON array of detected vendors |
| indicators_json | TEXT | JSON object {waf, captcha, botdet} |
| features_json | TEXT | JSON object of security headers |
| tls_version | TEXT | TLS version string |
| tls_cipher | TEXT | Cipher suite name |
| http_status | INTEGER | HTTP response code |
| recommendation_json | TEXT | JSON recommendation {tool, proxy_tier, fingerprint} |

Indexes: `domain`, `probed_at`

Cache TTL: 24h (probes older than 24h trigger a fresh probe unless `force=true`)

---

### `proxy_use`

Tracks proxy usage per host for rotation health.

| Column | Type | Description |
|--------|------|-------------|
| proxy_url | TEXT | Proxy endpoint |
| host | TEXT | Target hostname |
| ts | INTEGER | Unix timestamp |
| status | INTEGER | HTTP status returned |

Index: `(proxy_url, host, ts)`

---

### `risk_events`

Runtime risk events — one row per scraped response analysed by `RiskMiddleware`.
Added in Step 2.3.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| job_id | TEXT | Scrapy job ID (16-hex) — nullable for standalone use |
| domain | TEXT NOT NULL | Extracted from URL |
| url | TEXT NOT NULL | Full request URL |
| ts | TEXT NOT NULL | ISO 8601 UTC timestamp |
| http_status | INTEGER | HTTP status code |
| risk_score | REAL NOT NULL | 0.0–1.0 runtime risk score |
| vendors_json | TEXT | JSON array of detected WAF/bot vendors |
| markers_json | TEXT | JSON object {waf, captcha, botdet, status} hit counts |
| response_size | INTEGER | Response body size in bytes |
| duration_ms | INTEGER | Request duration in milliseconds |

Indexes: `domain`, `ts`, `job_id`

Queried by: `GET /risk/{domain}?hours=N` (aggregation per domain)

---

## Escalation mapping (Step 2.3+)

Risk scores from `risk_events` drive escalation decisions:

| avg_risk | Suggested action |
|----------|-----------------|
| < 0.2 | scrapy + datacenter proxy |
| 0.2–0.5 | scrapy + residential proxy |
| 0.5–0.8 | crawl4ai + residential |
| ≥ 0.8 | screenshot + residential |
