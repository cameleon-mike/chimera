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

### `epid_stats`

Aggregated ePID statistics: price quartiles and avg sell time. Populated by `POST /epid/ingest`.

| Column | Type | Description |
|--------|------|-------------|
| epid | TEXT PK | eBay Product Identifier |
| brand | TEXT | First word extracted from title |
| model | TEXT | Words 2-3 extracted from title |
| total_items | INTEGER | Number of ingested items for this ePID |
| currency | TEXT | Currency (EUR, GBP, etc.) |
| median_price | REAL | Median price across items |
| q1_price | REAL | First quartile price |
| q2_price | REAL | Second quartile (= median) |
| q3_price | REAL | Third quartile price |
| q4_price | REAL | Maximum price |
| avg_sell_days | REAL | Mean selling time in days (null if no sold items) |
| min_sell_days | REAL | Minimum selling time in days |
| max_sell_days | REAL | Maximum selling time in days |
| sell_days_sample | INTEGER | Number of items used to compute avg_sell_days |
| last_updated | TEXT | ISO 8601 UTC timestamp of last recompute |

Upsert strategy: `INSERT OR REPLACE` — fully recomputed on each ingest batch.

---

### `scraped_items`

Raw item store — one row per scraped listing (deduplicated by URL).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| epid | TEXT | eBay Product Identifier (nullable for non-eBay sources) |
| title | TEXT | Listing title |
| price_value | REAL | Numeric price |
| price_currency | TEXT | Currency code |
| start_date | TEXT | Listing creation date (ISO 8601) |
| end_date | TEXT | Sold/ended date (ISO 8601) — null for active listings |
| source | TEXT | Data source: "ebay", "2ememain", "watchcount" |
| url | TEXT UNIQUE | Canonical URL — deduplication key |
| scraped_at | TEXT | Ingest timestamp (ISO 8601 UTC) |

Index: `epid` (for per-ePID queries in `recompute_all_stats`)

Inserted by: `POST /epid/ingest` and `GET /ebay/search?ingest=true`
