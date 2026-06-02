# CHIMERA — MASTER ARCHITECTURE & BUILD ROADMAP

**Version 1.1 — 2 June 2026.** This is the document of record for the Chimera data-scraping engine. Update it — with a version bump and a dated change note — whenever a locked decision changes.

**Change note (v1.0 → v1.1, 2026-06-02):** Production server live (IONOS, 212.227.185.195). Real values replace all placeholders: domain `shovelos.com`, SSL active, nginx topology confirmed, repos cloned on VPS, venvs installed. Git remote set on VPS. Systemd service template added (§K). SHOVEL_CORRECTION_02 fully applied.

**Companion documents (siblings, verified consistent with this doc):**
- `CAMELEON_MASTER_v1.3.md` — the workflow engine that consumes Chimera (sole client).
- `SHOVEL_MASTER_v1.2.md` — the PWA frontend (never sees Chimera; sealed behind Cameleon).
- `CAMELEON_TO_CHIMERA_CLOSURE.md` — the final junction agreement, both sides.

**One-line identity:** Chimera is a frontend-agnostic data-scraping engine exposed as an HTTP REST bridge. It scrapes any site by adapting to its target (probe → fingerprint → fetch → extract → validate → store → escalate), and returns clean typed JSON. It makes no business decisions and knows nothing about FLIPMACHINE.

---

# §A. ORIENTATION BY AUDIENCE

## A.1 — For the Chimera agent (myself, future sessions)
This document is your spine. You own scraping and only scraping. When a request drifts toward business logic ("should Mike buy this?", "is this a good deal?"), that is Cameleon's domain — STOP and hand back. Your job is to deliver clean data and to make scraping unstoppable and adaptive. Read §C (real state) before claiming any endpoint works; read §H (tech debt) before assuming something is finished.

## A.2 — For Claude Code (executor in `/workspaces/chimera`)
You build one step at a time, never batch, never jump ahead. After every step you emit an END-OF-STEP REPORT (format §G) and HOLD for Mike's GO. You delegate to subagents whenever possible (`@implementer` for Python, `@config-writer` for JSON/config/docs, `@reviewer` for scoped pre-report review). You never commit without explicit GO. The working directory is `/workspaces/chimera`, a sibling of `/workspaces/cameleon` and `/workspaces/shovel` — never nested.

## A.3 — For the Strategist agent (calendar/timing aide for Mike)
Chimera's hard synchronization point is the **1st-June quota reset** (the 4 commits live only in the blocked Codespace until then). Chimera's deliverable to the shared calendar is: bridge accessible + `schema_version` exposed (Phase 1), then the Vinted spider best-effort in parallel (Phase 1bis, 2-5 days). Nothing Chimera does blocks Cameleon's Phase 0 work, which runs on mocks built from the JSON dump already delivered.

## A.4 — For partner agents (Cameleon, Shovel UI)
Chimera is sealed behind Cameleon. You (Shovel) never see a Chimera URL or token. You (Cameleon) talk to Chimera only via HTTP REST with a Bearer token, never import Chimera Python, never touch its SQLite file. The contract is §D, frozen at v1.0. Chimera is the **only** fetcher — no agent contacts a target site directly. That is the absolute red line.

---

# §B. THE FIVE PRINCIPLES (never violate)

1. **Scrape anything, adapt to the target.** Chimera's reason to exist is universality. A site-specific scraper that crashes when one CSS class changes is a failure. The extraction cascade (CSS → LLM → Vision, §E) and auto-repair exist precisely so that a layout change degrades gracefully instead of breaking.

2. **Fetcher, never decider.** Chimera retrieves and structures data. It never judges whether a price is good, whether to buy, whether to alert. Those are Cameleon's. If code starts to encode business rules, that is the violation.

3. **Null, never absent.** Every documented field is always present in the JSON; unknown values are `null`, never omitted. This is anti-KeyError insurance for Cameleon. `avg_sell_days`, `epid`, `end_date` are the usual nulls.

4. **No silent 500.** Every endpoint wraps its body. A scrape that fails returns `200` with `total_items:0` and a structured reason — never an unhandled exception surfacing as a 500. The bridge stays up; `/health` answers in < 500ms.

5. **Invisible to the user.** Chimera has no UI-facing surface. No base URL, no token, no string "chimera" ever reaches the PWA. The frontend talks to Cameleon; Cameleon proxies to Chimera server-side.

---

# §C. REAL STATE (what exists, and from which environment it works)

**This section distinguishes "code exists" from "validated in production." Read it before trusting any endpoint.**

## C.1 — Build state
- **Sessions 1-4 complete.** Commits `d280723` (S1) · `950ad1f` (S2) · `44c29bf` (S3) · `1bf4e6b` (S4).
- **438 tests pass, 1 xfailed.** Manifest `v0.7.5`.
- **RECOVERED (2026-06-02):** The 4 commits survived in the `expert-spork` Codespace under `/workspaces/chimera`. They have been pushed to `https://github.com/cameleon-mike/chimera` and cloned on the production VPS. The code is now safe. 438 tests confirmed passing on VPS.

## C.2 — Endpoints: functional and tested in real conditions (work from any IP)
These returned real data in validated E2E sessions:
- `GET /health` — always OK.
- `GET /capabilities` — returns manifest v0.7.5 (schema_version added Phase 1).
- `GET /probe/{domain}` — risk score + recommendation; tested on ebay.fr, httpbin, discord.
- `GET /ebay/search` — **83 items** for "wacom cintiq 16" validated.
- `GET /aggregate/search` — **271 items** eBay validated, sources `{ebay:271, 2ememain:0}`.
- `GET /epid/stats/{epid}` — **median_price 384.8 EUR** validated for epid 12028395711.
- `POST /epid/ingest` — 83 items ingested validated.
- `POST /escalate` — recommendation by job_id validated.
- `GET /escalation/policy` — full policy returned.
- `GET /factory/profiles`, `POST /factory/create`, `GET /factory/stats` — validated.

## C.3 — Endpoints: code complete but BLOCKED from Codespace Azure (prod-only)
These work in code but cannot be validated from the Azure Codespace because Bright Data residential AND datacenter are both blacklisted from the Microsoft Azure IP range. They will work from a real VPS:
- `GET /watchcount/search` — reCAPTCHA from Azure (sold-dates source).
- `GET /2ememain/search` — 403 from Azure.
- `POST /run-tool` with `tool=screenshot` — proxy blocked from Azure.
- `POST /run-tool` with `tool=bypass_waf` — FlareSolverr runs, proxy blocked from Azure.

## C.4 — Endpoints: code complete, not yet validated live end-to-end
- `POST /run-tool` with `tool=crawl4ai` — code OK, used as Vinted interim fetcher, full live pass pending.
- `GET /factory/recommend` — returns 404 until a profile reaches `ready` status (expected; no profile aged yet).
- `POST /factory/warm/{id}` — real warm-up sequence not yet run live.

## C.5 — To be delivered (Phase 1bis)
- `GET /vinted/search` — Vinted spider. Does not exist yet. 2-5 days post-reset, best-effort, in parallel, non-blocking for Cameleon.

---

# §D. JUNCTION CONTRACTS (locked v1.0)

## D.1 — What Chimera owes Cameleon
- Expose `schema_version` in `/capabilities` (added Phase 1, value `"1.0"`).
- Increment `schema_version` before any breaking change, with prior notification.
- Return `null` rather than omit a field (anti-KeyError).
- Never return an unhandled 500; failed scrapes return `200` with `total_items:0` + structured reason.
- `/health` responds in < 500ms when the service is up.
- Systemd auto-restart on crash.
- Remain invisible to the PWA (no UI-facing URL or token).

## D.2 — What Cameleon owes Chimera (recorded here for symmetry; Cameleon's doc is authoritative)
- Use Chimera **only via HTTP REST** (ChimeraClient); never import Chimera Python code.
- Bearer auth (`CHIMERA_AUTH_TOKEN` on Cameleon's side = the same value as Chimera's `BRIDGE_AUTH_TOKEN`; see note D.5).
- Gracefully handle all null fields; never assume presence.
- 3-retry exponential backoff (1s, 2s, 4s) + 60-minute stale mode.
- Read `epid_stats` **only via `/epid/stats/{epid}`** — never touch Chimera's SQLite file directly.
- Route ALL scraping through Chimera — no direct site contact from Cameleon code.
- Vinted interim: use `/run-tool` with `tool=crawl4ai` to fetch markdown, do LLM extraction Cameleon-side.

## D.3 — The Vinted red line (absolute)
Chimera is the **only fetcher**. Even before the Vinted spider exists, Cameleon does not contact vinted.fr directly. It calls `/run-tool crawl4ai` and Chimera does the fetch (proxy, stealth, escalation). Cameleon extracts from the returned markdown. When `/vinted/search` ships, Cameleon swaps the endpoint — zero architectural change. This red line is non-negotiable on the Chimera side.

## D.4 — schema_version commitment
`schema_version` lives in `/capabilities`. v1.0 covers the AggregatedItem and EpidStats shapes in §D.6. A breaking change (renamed field, changed type, removed field) increments the major version *before* rollout, with notice to Cameleon. Additive changes (new optional field, always nullable) do not require a major bump.

## D.5 — Token naming note
Chimera's internal env var is `BRIDGE_AUTH_TOKEN`. Cameleon's ChimeraClient reads it as `CHIMERA_AUTH_TOKEN`. **These are the same secret value**, named differently on each side. When Mike provisions the VPS he sets one token; each service's `.env` references it under its own name. No mismatch — just two labels for one secret.

## D.6 — Frozen data shapes (contract v1.0)

**AggregatedItem** (returned by `/aggregate/search`, and by `/ebay/search`, `/2ememain/search`, future `/vinted/search`):
```
title           str     required
price.value     float   required
price.currency  str     required
source          str     "ebay" | "2ememain" | "vinted"
epid            str?    null when absent (~84% null on eBay.fr)
start_date      str?    ISO date, null when absent
end_date        str?    null when item still listed (always null on eBay Browse API)
photo_url       str?    null when absent
link            str     required
```

**EpidStats** (returned by `/epid/stats/{epid}`):
```
epid             str     required
brand            str?    null if not detected from title
model            str?    null if not detected from title
total_items      int     required
currency         str     required
median_price     float   required
q1_price         float   required (bottom of market)
q2_price         float   required
q3_price         float   required
q4_price         float   required (top of market)
avg_sell_days    float?  null until production sold-dates available
min_sell_days    float?  null when avg_sell_days null
max_sell_days    float?  null when avg_sell_days null
sell_days_sample int     0 when avg_sell_days null
last_updated     str     required, ISO timestamp
```

**Nullability rules (absolute):** never omit a field; always `null` when unknown; Cameleon can `.get()` without KeyError.

---

# §E. THE EXTRACTION CASCADE (Chimera's core: scrape anything, adapt)

The defining capability. Three levels, fastest to most robust, with auto-repair.

## E.1 — Level 1: structured CSS extraction
A per-site JSON schema (`baseSelector` + fields with `selector`/`type`/`attribute`). Fast, deterministic, free. Fragile if the site changes class names (Vinted obfuscates `data-testid` regularly). This is the first attempt.

## E.2 — Level 2: LLM extraction (fallback when CSS yields 0 or fails validation)
Crawl4AI returns the page markdown → sent to Groq (`llama-4-scout`, free tier) with a per-site extraction prompt → returns a JSON array. Robust to layout changes because the LLM understands semantics, not syntax. Latency 500-2000ms, low token cost.

## E.3 — Level 3: Vision extraction (ultimate fallback)
When markdown + LLM both fail (heavy JS SPA): screenshot PNG → Groq Vision or Claude Vision with an extraction prompt → JSON array. Slowest, used only when needed.

## E.4 — Auto-repair of the CSS schema
When LLM (L2) succeeds but CSS (L1) failed, Chimera regenerates the CSS selector via LLM and updates the schema JSON automatically. Next scrape, CSS works again. Example: Vinted renames `item-card` → `product-card`; CSS returns 0 → LLM extracts 45 → new selector generated → schema updated → following scrape uses CSS again. This is what makes the scraper self-healing rather than brittle.

## E.5 — Learning loop (future, Step 6.6)
A `skill_registry` SQLite table tracks per-site selector success rates. The most reliable selector is used first; below 60% success it is purged and re-learned. Hermes-inspired. Logged as future work, not v1.

---

# §F. ARCHITECTURE & TECH STACK

## F.1 — Layered architecture
```
SHOVEL (PWA)              ← never sees Chimera
    ↓ HTTPS (Cameleon only)
CAMELEON (LangGraph)      ← only Chimera client
    ↓ HTTP REST + Bearer
CHIMERA BRIDGE (FastAPI :8080)
    Auth → Endpoints → RQ queue → Workers
                          ↓
                     Redis :6379
   ↓          ↓          ↓            ↓
 Scrapy   Playwright  Crawl4AI    FlareSolverr
 (HTTP)   (browser)  (LLM-ready)  (WAF bypass)
   ↓          ↓          ↓            ↓
            Bright Data proxies (residential :33335)
                          ↓
                  Target sites
```

## F.2 — Tech stack (locked — do not substitute without explicit operator approval)
- **Python 3.12**, FastAPI bridge, Redis + RQ job queue.
- **Scrapy 2.16** (HTTP tools; note `start_requests()` → `async def start()` API change handled).
- **Playwright 1.60** + Chromium (browser tools, stealth).
- **Crawl4AI** (Chromium headless, markdown + JsonCssExtractionStrategy).
- **Firecrawl** (self-hosted Docker, 4 services, port 6381).
- **FlareSolverr 3.4.6** (Docker, port 8191, Cloudflare bypass).
- **Bright Data** residential + datacenter proxies (port 33335).
- **Groq** (`llama-4-scout`) for LLM extraction + Vision.
- **SQLite** (`storage/risk_db.sqlite`) for risk events, profiles, epid_stats, scraped_items.
- **APScheduler** for the Account Factory daily cron.
- **systemd** for production process management + auto-restart.

## F.3 — The escalation chain (probe-driven tool selection)
```
risk < 0.2   → scrapy, datacenter proxy
0.2 – 0.5    → scrapy, residential proxy
0.5 – 0.8    → crawl4ai (Chromium headless)
0.8 – 1.0    → screenshot (Playwright full stealth, aged profile)
+ Cloudflare → FlareSolverr first (returns cf_clearance, valid 30-60 min)
```

## F.4 — Scrapy middleware order (locked)
- 390 `RotateUAMiddleware` — UA + ordered headers from pool; respects session_id.
- 410 `RotateProxyMiddleware` — Bright Data proxy; respects session_id country.
- 543 `HumanDelayMiddleware` — log-normal delay (mean 1.5s, jitter 0.7).
- 900 `RiskMiddleware` — analyses each response, scores risk, logs to SQLite, emits escalation hint.

## F.5 — The Account Factory (profile lifecycle)
```
CREATE (0)    UA + timezone + locale configured
WARMING (1-7d) visits local sites (rtbf.be, lesoir.be, google),
              collects _ga/_fbp/cf_clearance, installs uBlock+Honey
READY (7d+)   usable in production
SENIOR (30d+) maximum trust, hard sites
RECYCLE (90d+) full refresh or replace
```
Rule: 1 profile = 1 country = 1 proxy country, always. APScheduler cron 09:00 UTC. `profiles` table in SQLite.

## F.6 — Repo & filesystem
- Working dir: `/workspaces/chimera` on VPS (IONOS 212.227.185.195) and Codespace `expert-spork`. Sibling of `cameleon`, `shovel`; never nested.
- `scraper.env` — gitignored; holds `BRIDGE_AUTH_TOKEN`, eBay keys, Groq key, Bright Data creds. To be created on VPS (see §K.2).
- `storage/risk_db.sqlite` — gitignored; local DB.
- `.venv/` — recreated per environment (`pip install -e .` + playwright + groq + apscheduler).

---

# §G. STEP REPORT FORMAT (Claude Code, after every step)

```
═══════════════════════════════════════════════
STEP REPORT — Session X · Step Y.Z
═══════════════════════════════════════════════
TOKEN ACCOUNTING (brief table: agent → tokens)

✅ DELIVERED (files created / modified)

🧪 TESTS
  make test → N passed, 1 xfailed
  E2E results (real curl outputs, key fields)

🐛 BUGS / DEVIATIONS (all fixed before report, or flagged)

✔️ DECISIONS (Dn = …; or "none")

🔜 NEXT STEP (per §I roadmap)

▶️ AUTHORIZATION REQUIRED: GO Step Y.Z+1
   No further step without Mike's GO.
═══════════════════════════════════════════════
```

Delegation is mandatory: Claude Code (Sonnet orchestrator) does orchestration + report only; `@implementer` writes Python; `@config-writer` writes JSON/config/docs; `@reviewer` does scoped pre-report review of named files only. No self-coding beyond quick diagnosis.

---

# §H. TECHNICAL DEBT (open, not blocking MVP)

- **TD-19** — FlareSolverr sessions not cleaned up on failure (session_id leak). Target: Session 6 housekeeping.
- **TD-20** — No automatic retry on FlareSolverr challenge timeout. Target: Session 4/5.
- **TD-21** — APScheduler factory cron has no overlap guard (two runs could collide if one is slow). Target: Session 5.
- **TD-22** — `ProfileManager._save_meta()` is O(n) on the full profile set; fine at current volume, slow at large parc. Target: when profile count grows.
- **TD-23** — eBay sold dates via Marketplace Insights API: refused for new developer accounts. WatchCount is the workaround (blocked Azure, OK prod). Until then `avg_sell_days` stays null. Status: monitoring.
- **TD-24** — `recompute_all_stats` recomputes all epids rather than only touched ones after `/epid/ingest`. O(n) but correct; acceptable at current volume. Target: Session 5.

None of these affect FLIPMACHINE correctness for the MVP.

---

# §I. ROADMAP

## I.1 — Shared calendar (locked, consistent with Cameleon §13 and Shovel §29)

| When | Chimera (this engine) | Cameleon | Shovel UI |
|---|---|---|---|
| **30 May → 1 Jun** | Forced quota rest; JSON dump delivered (done) | 4 prep deliverables on mocks | Phase 0 (scaffold + spine) |
| **Week of 2 Jun** | ✅ **Phase 1 DONE**: git push completed, VPS live, venv installed. `schema_version` to add. **Phase 1bis**: Vinted spider in parallel (best-effort) | FLIPMACHINE workflow on eBay+2ememain | Phase 1 (shell) + Phase 2 (data layer) |
| **Week of 9 Jun** | Vinted spider in prod monitoring (if 1bis delivered); stable | Delivers `CAMELEON_API_CONTRACT_v1.md`; Vinted branching | 🔒 GATE → Phase 3 |
| **Week of 16 Jun** | Stable; Step 5.6 web `/ui` (optional, non-blocking) | Endpoints exposed + tested | Phase 4 + Phase 5 |
| **Week of 23 Jun** | Stable; junction validation support | Junction validation | Phase 5 join + Phase 6; E2E on 3 products |
| **End of June 2026** | — | — | **MVP FLIPMACHINE functional & validated** |

Two mandatory rendezvous: Phase-1 connectivity validation (after reset), and the Phase-5 join (week of 23 June). Otherwise async; any emergent point triggers a one-off exchange via Mike.

## I.2 — Hard checkpoints
- **1st-June quota reset** — the only hard dependency. Until then the 4 commits are recoverable only by waiting (or paying the GitHub bill). After reset: `git push` recovers everything, then `schema_version` is added, then the bridge is made accessible from Cameleon's Codespace.
- **Phase-1 connectivity validation** — Cameleon runs 5 real curl calls (`/health`, `/capabilities` checking `schema_version`, `/probe/vinted.fr` replacing the estimate, `/aggregate/search?q=wacom+cintiq+16`, `/epid/stats/12028395711`). Any schema mismatch → immediate mock adjustment Cameleon-side.

## I.3 — Sessions remaining (Chimera build)

**Session 4.6 (Phase 1bis) — Universal Extractor + Vinted spider**
- `tools/extractors/universal_extractor.py` — CSS → LLM → Vision cascade with auto-repair (§E).
- Per-site schema JSON: `vinted_fr.json`, `ebay_fr.json`, `2ememain_be.json`.
- `GET /vinted/search` endpoint, returns AggregatedItem shape, `source:"vinted"`.
- `avg_sell_days` null → `velocity_flag=unknown` honored.
- Est. ~100k tokens, 2-5 days, best-effort, parallel, non-blocking for Cameleon.

**Session 5 — LangGraph integration support + Web UI**
- 5.1 ops_agent ↔ ChimeraClient support (Cameleon-side, Chimera assists on schema)
- 5.2 vision_agent ↔ screenshot pipeline
- 5.3 scraping_agent weekly cron
- 5.4 decision_agent support (data shape stability)
- 5.5 navigator_agent + technical dashboard
- 5.6 Web HTTP UI (Alpine.js + Tailwind CDN, no build), accessible `:8090/ui` — optional, the PWA is the real UI; this is a Chimera-internal monitoring surface only.

**Session 6 — Production**
- 6.1 Nginx + TLS + IP whitelist (prerequisite for PWA install; see §J)
- 6.2 Audit + storage encryption
- 6.3 Monitoring (Prometheus)
- 6.4 Chaos testing
- 6.5 Final documentation
- 6.6 Learning Loop (skill_registry, selector success tracking, §E.5)

**Session 7 — REMOVED for Chimera.** The PWA (Shovel) is built in `/workspaces/shovel` by the UI agent, served by nginx from the same VPS. Chimera's only contribution is being reachable server-side via `/api/chimera/*`. The old Chimera-Session-7 (Capacitor APK) is deleted: the decision is PWA, not APK (§J).

## I.4 — Endpoints used by Cameleon for FLIPMACHINE
Ready now: `/health`, `/capabilities`, `/probe/{domain}`, `/ebay/search`, `/aggregate/search` (with `ingest` param), `/epid/stats/{epid}`, `/epid/ingest`, `/escalate`, `/run-tool` (crawl4ai for Vinted interim). To deliver Phase 1bis: `/vinted/search`. Not used by FLIPMACHINE v1: `/watchcount/search` (until avg_sell_days fills in prod), `/factory/*` (internal), `/run-tool screenshot` (escalation only).

---

# §J. KEY DECISIONS (locked by Mike, 30 May)

1. **Stale mode N = 60 minutes.** Cameleon's concern; Chimera guarantees `/health` < 500ms and systemd auto-restart so Cameleon can detect reachability quickly.
2. **3 MVP test products** = Wacom Cintiq 16 (GTIN-dense), GoPro (action camera), SteelSeries Apex Pro TKL (gaming). All present on eBay; good scoring stress test.
3. **URL Chimera prod** = `https://shovelos.com` (LIVE as of 2026-06-02). Let's Encrypt SSL valid until 2026-08-31, auto-renewal configured. DNS propagated and confirmed. ChimeraClient uses `https://shovelos.com/api/chimera` in production, `http://localhost:8080` in dev.
4. **PWA hosting** = same VPS (IONOS 212.227.185.195), nginx live topology:
```
https://shovelos.com/api/chimera/*   → Chimera bridge :8080   (server-side ONLY)
https://shovelos.com/api/cameleon/*  → Cameleon FastAPI :8000  (only path PWA uses)
https://shovelos.com/                → static Shovel PWA /workspaces/shovel/dist/
nginx config: /etc/nginx/sites-available/shovel
```
No CORS, simple auth, all centralized.

**Decision on PWA vs APK (revised by Chimera, accepted all sides):** Shovel = PWA, not Capacitor APK. Reasons: same React/Vite code, installable from Chrome Android without Play Store, instant updates, works in HTTP locally during dev. Consequence for Chimera: Session 7 (APK) is removed; the PWA lives in `/workspaces/shovel`. Prerequisite: Session 6.1 (Nginx + TLS) precedes any PWA install test — already correctly ordered.

---

# §K. RESUME RITUAL (for any next Chimera session)

## K.0 — Production VPS (primary environment from v1.1)
```bash
# SSH into the VPS
ssh root@212.227.185.195

# Working directory
cd /workspaces/chimera

# Git remote (SSH, cameleon-mike account)
# git remote: git@github-cameleon-mike:cameleon-mike/chimera.git
# SSH key: ~/.ssh/id_ed25519 (github-cameleon-mike alias in ~/.ssh/config)

# Activate venv (already installed)
source .venv/bin/activate

# Verify env file
grep -c "=" scraper.env    # all keys must be present

# Start bridge
rm -f .bridge.pid .worker.pid
make start
export TOKEN=$(grep BRIDGE_AUTH_TOKEN scraper.env | cut -d= -f2)
curl -s https://shovelos.com/api/chimera/capabilities | python3 -c   "import sys,json;d=json.load(sys.stdin);print(d['manifest_version'], d.get('schema_version'))"
make stop
```

## K.1 — systemd service (to be configured on VPS)
```ini
# /etc/systemd/system/chimera-bridge.service
[Unit]
Description=Chimera Bridge FastAPI
After=redis.service network.target

[Service]
WorkingDirectory=/workspaces/chimera
EnvironmentFile=/workspaces/chimera/scraper.env
ExecStart=/workspaces/chimera/.venv/bin/uvicorn bridge.app:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
```
```bash
# Enable:
systemctl daemon-reload
systemctl enable chimera-bridge
systemctl start chimera-bridge
systemctl status chimera-bridge
```

## K.2 — scraper.env (to create on VPS)
```bash
# Keys required — fill from your credentials:
BRIDGE_AUTH_TOKEN=<generate a strong random token>
EBAY_APP_ID_1=<your-ebay-app-id>
EBAY_CERT_ID_1=<your-ebay-cert-id>
EBAY_DEFAULT_MARKETPLACE=EBAY_FR
GROQ_API_KEY=<your Groq key>
BRIGHTDATA_USERNAME=brd-customer-hl_86614cff-zone-chimera_residential
BRIGHTDATA_PASSWORD=<current password>
BRIGHTDATA_HOST=brd.superproxy.io
BRIGHTDATA_PORT=33335
BRIGHTDATA_DC_USERNAME=brd-customer-hl_86614cff-zone-chimera_datacenter
BRIGHTDATA_DC_PASSWORD=<current password>
FACTORY_CRON_ENABLED=false
FACTORY_NEW_PROFILES_PER_DAY=2
```

## K.3 — Iron rule (learned the hard way)
**Push after EVERY step.** Never let commits live only in a Codespace or container. After every step GO:
```bash
git add -A && git commit -m "Session X · Step Y.Z — description" && git push
```
The 4-session codebase was nearly lost to a billing-block container reclaim. It was recovered from `expert-spork` codespace. **Never again.**

```bash
# 1. Get into the Codespace (post 1st-June reset)
gh codespace ssh -c <chimera-codespace-name>

# 2. Working directory
cd /workspaces/chimera

# 3. Recover code if fresh environment
git log --oneline          # expect 4 commits: d280723, 950ad1f, 44c29bf, 1bf4e6b
# if missing: git push was never done — recover from blocked Codespace first

# 4. Environment
source .venv/bin/activate 2>/dev/null || \
  (python -m venv .venv && source .venv/bin/activate && \
   pip install -e . && pip install playwright groq apscheduler && \
   python -m playwright install chromium)

# 5. Verify env file
grep -c "=" scraper.env    # expect the full set of keys

# 6. Clean stale PIDs (frequent gotcha — bridge won't start with stale .pid)
rm -f .bridge.pid .worker.pid

# 7. Start + verify
make start
export TOKEN=$(grep BRIDGE_AUTH_TOKEN scraper.env | cut -d= -f2)
curl -s http://127.0.0.1:8080/capabilities | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(d['manifest_version'], d.get('schema_version'))"
make stop

# 8. Run tests
make test                  # expect 438 passed, 1 xfailed (more after Session 4.6)
```

**File transfer Termux → Codespace (the working method; `gh codespace cp` is broken, adds bad quotes):**
```bash
gh codespace ssh -c <name> -- "cat > /workspaces/chimera/docs/FILE.md" < /storage/emulated/0/Download/FILE.md
```

**Stale-PID gotcha:** the single most frequent start failure is a leftover `.bridge.pid` / `.worker.pid`. `make start` reports "Bridge failed to come up" or "already running" on a dead PID. Always `rm -f .bridge.pid .worker.pid` first.

---

# §L. GLOSSARY (aligned with Cameleon §G and Shovel)

- **Chimera** — this data-scraping engine, `/workspaces/chimera`. Sealed behind Cameleon.
- **Cameleon** — workflow validation engine, `/workspaces/cameleon`. Chimera's only client.
- **Shovel** — PWA frontend, `/workspaces/shovel`. Never sees Chimera.
- **FLIPMACHINE** — first production workflow (scrape Vinted → score vs eBay/2ememain median → ranked deals). Chimera supplies data; it does not know the term operationally.
- **bridge** — the FastAPI HTTP server (`:8080`) that is Chimera's single entry point.
- **probe** — pre-scrape site analysis returning a risk_score (0-1) and a tool recommendation.
- **risk_score** — 0-1 measure of site protection, drives the escalation chain.
- **escalation chain** — scrapy → crawl4ai → screenshot → bypass_waf, selected by risk_score.
- **extraction cascade** — CSS → LLM → Vision, with auto-repair (§E). The core adaptability mechanism.
- **auto-repair** — regenerating a CSS selector via LLM when CSS fails but LLM succeeds.
- **Account Factory** — profile creation + aging subsystem (CREATE→WARMING→READY→SENIOR→RECYCLE).
- **session_id / SessionManager** — Redis sticky session: fixed fingerprint + fixed proxy + persistent cookies, 30-min TTL.
- **fingerprint** — coherent UA + headers + canvas + WebGL identity for a browser session.
- **cf_clearance** — Cloudflare clearance cookie returned by FlareSolverr, valid 30-60 min.
- **AggregatedItem / EpidStats** — the two frozen v1.0 data shapes (§D.6).
- **schema_version** — versioning field in `/capabilities`; mirrors Cameleon's pattern.
- **ePID** — eBay Product ID; null on ~84% of eBay.fr items.
- **avg_sell_days** — mean (end_date − start_date); null until production sold-dates available.
- **Bright Data** — residential/datacenter proxy provider; both tiers blacklisted from Azure (works from VPS).
- **BRIDGE_AUTH_TOKEN / CHIMERA_AUTH_TOKEN** — the same secret, named differently on Chimera and Cameleon sides.
- **red line** — Chimera is the only fetcher; no agent contacts a target site directly. Absolute.

**Discipline vocabulary (common across all 3 agents):** spine principle (no component certifies itself) · no-silent-lie (halt/null, never invent) · one-step-at-a-time · STOP-and-signal · auto-correction documented publicly (version bumps, no silent rewrites).

---

*End of CHIMERA_MASTER_v1.1. This is the document of record. Update it — with a version bump and a dated change note — whenever a locked decision changes. Updated 2 June 2026 with SHOVEL_CORRECTION_02 production values. Verified consistent with CAMELEON_MASTER_v1.3 and SHOVEL_MASTER_v1.2: shared calendar aligned, junction contract v1.0 identical both sides, nginx topology identical, four Mike-decisions identical, PWA-not-APK decision propagated, snake_case + schema_version + Bearer conventions aligned, red line acknowledged.*
