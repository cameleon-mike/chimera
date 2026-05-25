# Chimera — Legal & Terms of Service posture

> Initial version — Step 2.5 (2026-05-23). Finalized in Step 6.5.

---

## 1. Principle of minimal footprint

Chimera is a **tool**, not an actor. Every crawl decision (which domain, which tool
tier, which proxy) is made by the operator (cameleon / SecondPulse). Chimera enforces
the operator's stated policy — it does not decide autonomously to scrape anything.

---

## 2. Default posture

| Setting | Default | Override path |
|---------|---------|---------------|
| `respect_robots` | **true** — robots.txt always obeyed | Set `respect_robots: false` in `/run-tool` config, logged to `audit.jsonl` |
| Crawl rate | Scrapy `DOWNLOAD_DELAY 1.5 s` + autothrottle | `settings.DOWNLOAD_DELAY` in job config |
| PII storage | None beyond job metadata | Do not pass credentials in URL or headers unless necessary |
| Credentials | `.env` / `scraper.env` only — never committed | See `infra/systemd/chimera.env` |
| Cookies | `storage/cookies/` only — never in results JSON | — |

---

## 3. Tool escalation — legal considerations

Chimera's escalation ladder raises the intensity of interaction with a target:

| Tier | Tool | Legal note |
|------|------|-----------|
| 0 — low risk | `scrapy` datacenter | Standard HTTP; least intrusive |
| 1 — medium risk | `scrapy` residential | Residential proxy; still public HTTP |
| 2 — challenge | `crawl4ai` | Real browser render; mimics user visit |
| 3 — hard block | `screenshot` | Full-page capture; highest mimicry |
| 4 — CAPTCHA/JS challenge | `bypass_waf` | FlareSolverr — use only on explicitly authorized targets |

**Rule:** Tiers 3 and 4 require explicit per-domain authorization in the allowlist
below before cameleon may request them.

---

## 4. Domain allowlist

| Domain | Rationale | Authorized tiers (max) | Decision date | Notes |
|--------|-----------|------------------------|---------------|-------|
| httpbin.org | Testing / CI only | 4 | 2026-05-23 | Public test service |
| books.toscrape.com | Testing / CI only | 4 | 2026-05-23 | Dedicated scraping practice site |

---

## 5. Domain blocklist

| Domain | Reason | Date added | Notes |
|--------|--------|------------|-------|
| (none yet) | — | — | Add domains that must never be targeted |

---

## 6. Data retention

- Job results (`storage/results/*.json`) — retained for 7 days, then deleted by the
  operator's cron job (not yet automated; TD for Step 6.x).
- `risk_db.sqlite` (`risk_events`, `domain_probe`) — retained indefinitely for risk
  calibration. No PII stored in these tables.
- `audit.jsonl` — retained indefinitely. Contains job_id, tool, priority, URL only —
  no response bodies.
- Screenshots (`storage/screenshots/*.png`) — retained for 24 h, contain rendered
  page content; delete promptly if the page contains personal data.

---

## 7. Known limits and out-of-scope scenarios

- **Cloudflare Turnstile / Akamai Bot Manager (Sensor Data) / DataDome modern
  ML mode**: not defeatable without paid third-party solving services. Chimera will
  report the block via risk score; the operator must decide whether to abort or
  escalate to a paid solver.
- **Login flows requiring SMS, KYC, or Arkose Labs**: out of scope for automated
  scraping. Do not attempt.
- **Paywalled or subscription content**: operator's responsibility to hold a valid
  account/license. Chimera only executes — it does not create accounts.
- **GDPR / CCPA personal data**: if a spider yields rows containing names, emails, or
  other PII, the operator is responsible for lawful basis and data minimization.
  Chimera provides no automatic PII detection or redaction.

---

## 7b. FlareSolverr — usage constraints

FlareSolverr est utilisé **uniquement comme dernier recours** (risk_score ≥ 0.8,
escalade tier 4). Les contraintes suivantes s'appliquent :

- **Domaines autorisés uniquement** : seuls les domaines listés en section 4
  (Domain allowlist) peuvent être ciblés avec `bypass_waf`.
- **Contenu public uniquement** : ne jamais utiliser pour contourner des protections
  d'accès authentifié, des paywalls ou des systèmes de paiement.
- **Rate-limit volontaire** : un délai minimum de 30 secondes entre deux appels
  `bypass_waf` sur le même domaine est fortement recommandé.
- **Logs** : chaque utilisation de `bypass_waf` est tracée dans `audit.jsonl` avec
  `tool=bypass_waf`, `job_id` et URL. Ces logs sont conservés indéfiniment.
- **Turnstile / hCaptcha** : FlareSolverr résout les JS challenges Cloudflare mais
  **pas** les CAPTCHA visuels Turnstile ou hCaptcha sans solveur tiers configuré
  (`CAPTCHA_SOLVER=none` dans docker-compose). Ne pas promettre une résolution
  systématique.

---

## 8. Incident response

If Chimera triggers a rate-limit, IP ban, or legal notice from a target site:

1. Immediately add the domain to the blocklist above.
2. Stop any queued jobs for that domain via the RQ dashboard or `rq cancel`.
3. Rotate the affected proxy IPs.
4. Document the incident in this file under a new section "Incidents".

---

*Maintained by: Mike (SecondPulse). Review before each production deployment.*
