# CHIMERA SITEMAP

## Points d'entrée

### Onglets UI (6)
  search
  deals
  database
  dashboard
  settings
  stealth

### Groupes d'endpoints API
  /health, /metrics
  /capabilities
  /run-tool, /status/{job_id}, /result/{job_id}
  /risk/{domain}, /probe/{domain}, /escalate
  /ebay/search, /2ememain/search, /vinted/search, /aggregate/search, /watchcount/search
  /epid/stats/{epid}, /epid/search, /epid/ingest
  /flipmachine/score, /flipmachine/deals
  /navigator/run
  /dashboard
  /factory/profiles, /factory/create, /factory/warm/{id}, /factory/stats, /factory/recommend
  /stealth/run, /stealth/runs, /stealth/runs/{run_id}, /stealth/status/{run_id}
  /ui
  /download/{job_id}

## Onglets UI

### search
  Vues: Results grid, Pipeline stats
  Actions: RUN PIPELINE button, Query + max price filter
  Données: Deal cards (title, price, margin, decision), stats (duration, scraped, scored)
  Liens: VIEW link to marketplace

### deals
  Vues: Results table
  Actions: FIND DEALS button, Query input
  Données: Deals table (title, price, decision, confidence, margin, link)
  Liens: External VIEW link per row

### database
  Vues: ePID results table
  Actions: SEARCH button, Brand/model query input
  Données: ePID stats (EPID, brand, model, quartiles, avg days, item count)
  Liens: Click EPID to view history

### dashboard
  Vues: 6 cards (Bridge, Jobs, Scraping, Profiles, Proxy, — scoring summary)
  Actions: REFRESH button
  Données: System metrics (uptime, queue size, item count, profile counts, proxy status)
  Liens: Click card title for drill-down (not yet)

### settings
  Vues: Configuration form
  Actions: TEST CONNECTION button, Save on input
  Données: API URL field, Bearer token field, connection status message
  Liens: None

### stealth
  Vues: List view (runs table), Detail view (security grid + results + items table)
  Actions: [+ NEW RUN] button, REFRESH button, row click → detail, [LAUNCH], [CANCEL], ⬇ JSON, ⬇ CSV
  Données: Runs list (ID, query, source, items, status, duration), Detail (security map, results grid, items table)
  Liens: Row click → detail view, ← RETOUR to list, LAUNCH run modal shows vinted/ebay/2ememain sources, Proxy country select

## Endpoints API

### GET /health
  Params: none
  Retourne: Per-subsystem checks (redis, sqlite, scraper, proxy), metrics block, manifest version, uptime
  Appelle: redis.ping(), SQLite query (counts), proxy config check

### GET /metrics
  Params: none
  Retourne: Prometheus text/plain exposition format
  Appelle: None (metrics collection)

### GET /capabilities
  Params: none
  Retourne: tool_manifest.json (full schema)
  Appelle: mf.load_manifest()

### POST /run-tool
  Params: tool (enum: scrapy, firecrawl, crawl4ai, screenshot, bypass_waf, camoufox), url, config, priority, callback_url
  Retourne: {job_id, status: queued}
  Appelle: q.enqueue_job() → RQ queue

### GET /status/{job_id}
  Params: job_id
  Retourne: {job_id, status, tool, enqueued_at, started_at, finished_at}
  Appelle: q.fetch_job(), q.map_status()

### GET /result/{job_id}
  Params: job_id
  Retourne: {job_id, status, result (JSON), error}
  Appelle: q.fetch_job(), q.load_result() or job.return_value()

### GET /risk/{domain}
  Params: domain, hours (default 24)
  Retourne: Aggregated risk stats (avg_risk, max_risk, blocks, captchas, vendors_seen, recommendation)
  Appelle: SQLite query (risk_events table)

### GET /probe/{domain}
  Params: domain, force (bypass 24h cache)
  Retourne: {risk_score, vendors_detected, tls (version/cipher), features, indicators, recommendation, cached}
  Appelle: tools.probe.security_probe.probe_domain() or SQLite cache lookup

### POST /escalate
  Params: job_id
  Retourne: Escalation hint (needed, suggested_tool, avg_risk, max_risk, vendors_detected)
  Appelle: _compute_escalation() → SQLite risk_events query

### GET /escalation/policy
  Params: none
  Retourne: Thresholds + actions from tool_manifest.json
  Appelle: mf.get_escalation_policy()

### GET /download/{job_id}
  Params: job_id
  Retourne: PNG file
  Appelle: File read from screenshots_dir

### GET /ebay/search
  Params: q, marketplace (EBAY_FR/DE/GB/BE/NL), max_pages, ingest
  Retourne: {items (EbayItem list), total_items, api_calls_used, risk_scores, ts}
  Appelle: _run_scrapy_subprocess(), SQLite ingest if ingest=true

### GET /watchcount/search
  Params: q, marketplace
  Retourne: {items (WatchCountItem list), total_items, tool_used, recaptcha_detected, ts}
  Appelle: _run_scrapy_subprocess() → escalate to _run_screenshot_subprocess() + SoldDateExtractor.extract_from_screenshot()

### GET /2ememain/search
  Params: q, max_pages
  Retourne: {items (TwoememainItem list), total_items, tool_used, blocked, ts}
  Appelle: _run_scrapy_subprocess() → escalate to _run_screenshot_subprocess() + GroqVisionExtractor

### GET /vinted/search
  Params: q, marketplace, max_pages, tool (crawl4ai/scrapy)
  Retourne: {items (AggregatedItem list), total_items, blocked, tool_used, ts}
  Appelle: _run_crawl4ai_subprocess() + UniversalExtractor._llm_extract(), or _run_scrapy_subprocess()

### GET /aggregate/search
  Params: q, marketplace, max_pages, ingest
  Retourne: {items (merged + dedup), sources (count by source), duplicates_removed, ts}
  Appelle: fetch_ebay_raw(), fetch_2ememain_raw() in parallel, deduplicate(), optional SQLite ingest

### GET /epid/stats/{epid}
  Params: epid
  Retourne: EpidStats (quartiles, brand, model, avg_sell_days, last_updated)
  Appelle: SQLite query (epid_stats table)

### GET /epid/search
  Params: q
  Retourne: [EpidStats] (LIKE search on brand or model)
  Appelle: SQLite query (epid_stats table, pattern match)

### POST /epid/ingest
  Params: items (list of item dicts), source
  Retourne: {ingested, epids_updated}
  Appelle: SQLite insert into scraped_items, recompute_all_stats()

### GET /flipmachine/score
  Params: epid, price, shipping (default 15.0)
  Retourne: FlipScoreResponse (decision, confidence, margin_eur, margin_pct, reasoning)
  Appelle: FlipScorer.score() (tools.decision_agent.scorer)

### GET /flipmachine/deals
  Params: q, marketplace, max_price
  Retourne: DealsResponse {query, total_scored, deals_found, deals (top 10 BUY/OFFER)}
  Appelle: fetch_ebay_raw(), fetch_2ememain_raw(), deduplicate(), FlipScorer.score() for each item

### POST /navigator/run
  Params: query, max_price, marketplace
  Retourne: NavigatorRunResponse (deals found, pipeline stats: duration, items_scraped, items_scored)
  Appelle: NavigatorAgent.run() → probe marketplace, aggregate/search, FlipScorer.score()

### GET /dashboard
  Params: none
  Retourne: System state {bridge (version, uptime), jobs (queued, active, failed_1h), scraping (total_items, epids_tracked, last_scrape), profiles (by status), proxy}
  Appelle: RQ queue lookups, SQLite counts, profile status counts

### GET /factory/profiles
  Params: status (optional filter)
  Retourne: {profiles (list of profile objects)}
  Appelle: _get_factory().list_all_profiles()

### GET /factory/profiles/{profile_id}
  Params: profile_id
  Retourne: Single profile object
  Appelle: _get_factory()._get_profile()

### POST /factory/create
  Params: count, geo_id, proxy_country, ua_profile_id
  Retourne: {created (list of IDs), count}
  Appelle: _get_factory().create_profile() × count

### POST /factory/warm/{profile_id}
  Params: profile_id
  Retourne: Warm-up sequence report
  Appelle: _get_factory().run_warm_up()

### POST /factory/run-daily
  Params: new_profiles_count (optional)
  Retourne: Daily factory orchestration report (create + warm + age)
  Appelle: _get_factory().daily_factory_run()

### GET /factory/stats
  Params: none
  Retourne: {creating, warming, ready, senior} profile counts
  Appelle: _get_factory().get_stats()

### GET /factory/recommend
  Params: domain
  Retourne: Best warmed profile (geo-coherent, highest age)
  Appelle: _get_factory().get_best_for_domain(), validate_fqdn()

### POST /stealth/run
  Params: url, query, source, config {proxy_country, ingest}
  Retourne: StealthRunResponse {run_id, status, items (extracted), security_map, duration_ms}
  Appelle: StealthAgent.run() → 5 phases: ScanSecurity.scan(), CamoufoxRunner.fetch(), UniversalExtractor.extract(), SQLite persist + CSV/JSON report

### GET /stealth/runs
  Params: limit, offset, source (optional filter), status (optional filter)
  Retourne: {total, runs (list of StealthRunSummary)}
  Appelle: SQLite query (stealth_runs table, newest first)

### GET /stealth/runs/{run_id}
  Params: run_id
  Retourne: Full detail {run_id, created_at, url, query, source, status, duration_ms, security, config, http_status, html_len, items_count, items (list), report_path, error_msg, agent_id, ingest_done}
  Appelle: SQLite query (stealth_runs row), JSON.loads() on security_map + items_json

### GET /stealth/runs/{run_id}/report.json
  Params: run_id
  Retourne: JSON file (report)
  Appelle: _safe_report_path() → file read

### GET /stealth/runs/{run_id}/report.csv
  Params: run_id
  Retourne: CSV file (report)
  Appelle: _safe_report_path() → file read

### GET /stealth/status/{run_id}
  Params: run_id
  Retourne: StealthStatusResponse {run_id, status, phase, elapsed_ms}
  Appelle: SQLite query (stealth_runs row — status, created_at, duration_ms)

### GET /ui
  Params: none
  Retourne: Static HTML (index.html) — no auth required
  Appelle: FileResponse(index.html)
