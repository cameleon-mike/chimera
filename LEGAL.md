# Chimera — Legal & ToS posture

> Placeholder. Filled out properly in **Step 2.5** and finalized in **Step 6.5**.

## Default posture

- `respect_robots: true` by default — overrides logged to `audit.jsonl`.
- No PII storage beyond what is strictly required for the job.
- All credentials, tokens, and cookies are kept in `scraper.env` or `storage/cookies/` only — never committed.

## Domain allowlist (to be filled)

| Domain | Rationale | Decision date | Notes |
|--------|-----------|---------------|-------|

## Domain blocklist (to be filled)

| Domain | Reason | Decision date | Notes |
|--------|--------|---------------|-------|

## Known limits

- Cloudflare Turnstile / Akamai Bot Manager / DataDome modern: not defeatable without paid services.
- Login flows requiring SMS / KYC / Arkose Labs: out of scope.
