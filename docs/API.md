# Chimera API Reference

Base URL: `http://127.0.0.1:8080`; production: `https://shovelos.com/api/chimera`. Authentication: Bearer token from `scraper.env::BRIDGE_AUTH_TOKEN`.

## SYSTEM

### GET /health
Auth: public
Params: none
Returns: enriched liveness dict {status (ok|degraded), manifest_version, bridge_version, schema_version, uptime_seconds, checks{redis, sqlite, scraper, proxy}, metrics{total_items_scraped, epids_tracked, profiles_ready}}
Errors: none
Internal calls: q._redis_conn().ping(), sqlite counts

### GET /metrics
Auth: public
Params: none
Returns: Prometheus text exposition (text/plain)
Errors: none
Internal calls: metrics.collect_runtime_gauges()

### GET /capabilities
Auth: public
Params: none
Returns: full tool_manifest.json + schema_version
Errors: none
Internal calls: mf.load_manifest()

### GET /ui
Auth: public
Params: none
Returns: HTML (FileResponse index.html, the Alpine.js dashboard)
Errors: none
Internal calls: —

## SCRAPING ENGINE

### POST /run-tool
Auth: Bearer
Params: tool (enum, required) · url (str|list, required) · config (dict, optional) · priority (enum, default normal) · callback_url (str, optional)
Returns: {job_id, status:queued}
Errors: 401 · 422
Internal calls: q.enqueue_job()

### GET /status/{job_id}
Auth: Bearer
Params: job_id (str, path)
Returns: StatusResponse {job_id, status, ...}
Errors: 401
Internal calls: RQ job lookup

### GET /result/{job_id}
Auth: Bearer
Params: job_id (str, path)
Returns: ResultResponse {job_id, status, result payload}
Errors: 401
Internal calls: RQ result lookup

### GET /download/{job_id}
Auth: Bearer
Params: job_id (str, path)
Returns: result file (FileResponse)
Errors: 401 · 404 (no file)
Internal calls: —

## RISK & PROBE

### GET /probe/{domain}
Auth: Bearer
Params: domain (str, path) · force (bool, default false)
Returns: ProbeResponse {domain, risk_score, recommendation, vendors_detected, ...}
Errors: 401 · 422
Internal calls: _probe_domain()

### GET /risk/{domain}
Auth: Bearer
Params: domain (str, path) · hours (int, default 24)
Returns: RiskResponse aggregated risk history
Errors: 401 · 422
Internal calls: sqlite risk_events

### POST /escalate
Auth: Bearer
Params: none
Returns: EscalateResponse {action, next_tool, ...}
Errors: 401
Internal calls: _compute_escalation()

### GET /escalation/policy
Auth: public
Params: none
Returns: escalation policy from manifest
Errors: none
Internal calls: mf.get_escalation_policy()

## MARKETS

### GET /ebay/search
Auth: Bearer
Params: q (str, required) · marketplace (str, default EBAY_FR) · max_pages (int, default 3) · ingest (bool, default false)
Returns: EbaySearchResponse {total_items, items[]}
Errors: 401 · 422 · 503 · 504
Internal calls: eBay Browse API

### GET /watchcount/search
Auth: Bearer
Params: q (str, required) · marketplace (str, default EBAY_FR)
Returns: WatchCountSearchResponse (sold listings + dates)
Errors: 401 · 422
Internal calls: _ingest_sold_dates()

### GET /2ememain/search
Auth: Bearer
Params: q (str, required) · max_pages (int, default 3)
Returns: TwoememainSearchResponse {total_items, items[]}
Errors: 401 · 422 · 504
Internal calls: scrapy spider

### GET /vinted/search
Auth: Bearer
Params: q (str, required) · marketplace (str, default FR) · max_pages (int, default 3) · tool (str, default crawl4ai)
Returns: VintedSearchResponse {total_items, items[]}
Errors: 401 · 422 · 504
Internal calls: crawl4ai → UniversalExtractor

### GET /aggregate/search
Auth: Bearer
Params: q (str, required) · marketplace (str, default EBAY_FR) · max_pages (int, default 3) · ingest (bool, default false)
Returns: AggregateSearchResponse (merged multi-source items)
Errors: 401 · 422
Internal calls: ebay + market spiders + epid grouping

## EPID

### GET /epid/stats/{epid}
Auth: Bearer
Params: epid (str, path)
Returns: EpidStats
Errors: 401 · 404
Internal calls: _get_epid_conn()

### GET /epid/search
Auth: Bearer
Params: q (str, required)
Returns: list[EpidStats]
Errors: 401 · 422
Internal calls: _get_epid_conn()

### POST /epid/ingest
Auth: Bearer
Params: none
Returns: IngestResponse {ingested, epids_updated}
Errors: 401 · 422
Internal calls: _get_epid_conn() upsert

## FLIPMACHINE

### GET /flipmachine/score
Auth: Bearer
Params: epid (str, required) · price (float, required) · shipping (float, default 15.0)
Returns: FlipScoreResponse {decision, confidence, margin_eur, ...}
Errors: 401 · 404 (epid unknown) · 422
Internal calls: FlipScorer().score(), _get_epid_conn()

### GET /flipmachine/deals
Auth: Bearer
Params: q (str, required) · marketplace (str, default EBAY_FR) · max_price (float, optional)
Returns: DealsResponse {deals_found, total_scored, deals[]}
Errors: 401 · 422
Internal calls: FlipScorer().score(), _get_epid_conn()

### POST /navigator/run
Auth: Bearer
Params: none
Returns: NavigatorRunResponse {query, pipeline_ms, probe_risk, total_scraped, total_scored, deals[], summary}
Errors: 401 · 422
Internal calls: NavigatorAgent()

## DASHBOARD

### GET /dashboard
Auth: Bearer
Params: none
Returns: DashboardResponse {bridge{}, jobs{}, scraping{}, scoring{}, profiles{}}
Errors: 401
Internal calls: q._redis_conn(), sqlite aggregates

## FACTORY

### GET /factory/profiles
Auth: Bearer
Params: status (str, optional filter)
Returns: list of profiles
Errors: 401
Internal calls: ProfileManager

### GET /factory/profiles/{profile_id}
Auth: Bearer
Params: profile_id (str, path)
Returns: profile detail
Errors: 401 · 404
Internal calls: ProfileManager

### POST /factory/create
Auth: Bearer
Params: none
Returns: created profile
Errors: 401 · 422
Internal calls: ProfileManager

### POST /factory/warm/{profile_id}
Auth: Bearer
Params: profile_id (str, path)
Returns: warm-up result
Errors: 401
Internal calls: factory.run_warm_up()

### POST /factory/run-daily
Auth: Bearer
Params: none
Returns: daily run summary
Errors: 401
Internal calls: factory.daily_factory_run()

### GET /factory/stats
Auth: Bearer
Params: none
Returns: profile pool stats by status
Errors: 401
Internal calls: ProfileManager

### GET /factory/recommend
Auth: Bearer
Params: domain (str, required)
Returns: recommended profile for domain
Errors: 401 · 404 · 422
Internal calls: ProfileManager

## STEALTH

### POST /stealth/run
Auth: Bearer
Params: none
Returns: StealthRunResponse {run_id, status (success|error|captcha_blocked), security{}, result{}, report{}}
Errors: 401 · 422 · 504 (120s cap)
Internal calls: StealthAgent().run() via asyncio.to_thread — note: never 500, agent always returns structured status

### GET /stealth/runs
Auth: Bearer
Params: limit (int, default 20) · offset (int, default 0) · source (str, optional) · status (str, optional)
Returns: {total, runs[]}
Errors: 401
Internal calls: _get_epid_conn()

### GET /stealth/runs/{run_id}
Auth: Bearer
Params: run_id (str, path)
Returns: run detail + items[]
Errors: 401 · 404
Internal calls: _get_epid_conn()

### GET /stealth/runs/{run_id}/report.json
Auth: Bearer
Params: run_id (str, path)
Returns: report JSON (FileResponse)
Errors: 401 · 404 (report absent; path-traversal-safe)
Internal calls: _safe_report_path()

### GET /stealth/runs/{run_id}/report.csv
Auth: Bearer
Params: run_id (str, path)
Returns: report CSV (FileResponse, text/csv)
Errors: 401 · 404 (report absent; path-traversal-safe)
Internal calls: _safe_report_path()

### GET /stealth/status/{run_id}
Auth: Bearer
Params: run_id (str, path)
Returns: StealthStatusResponse {run_id, status, items_count, duration_ms, ...}
Errors: 401 · 404
Internal calls: _get_epid_conn()
