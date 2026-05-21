# Chimera

Hybrid production scraper — the first tool in the cameleon toolkit.

**Cameleon is the brain. Chimera is the hand.**

Cameleon decides strategy (which tool, which proxy tier, when to escalate, how to interpret a screenshot). Chimera executes, logs, returns. All configuration is discoverable by cameleon at runtime via `tool_manifest.json` → `/capabilities` → OpenAPI.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design. Four scraping engines (Scrapy → Firecrawl → Crawl4AI → Screenshot) sit behind a FastAPI bridge with Redis Queue dispatch, risk scoring, and auto-escalation.

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md). 6 sessions × 5 steps = 30 controlled checkpoints. Step Report required before each next step.

## Quick start (dev — Codespace)

```bash
cp .env.example scraper.env       # then edit BRIDGE_AUTH_TOKEN
make install                      # python deps in .venv
make redis-start                  # background Redis
make check-env                    # validates everything
```

## Quick start (prod — Ubuntu 24.04 server)

```bash
sudo mkdir -p /opt/scraper-pack && sudo chown $USER /opt/scraper-pack
git clone <repo> /opt/scraper-pack && cd /opt/scraper-pack
cp .env.example scraper.env       # fill in real token + paths
make install
sudo systemctl enable --now redis-server
sudo cp infra/systemd/*.service /etc/systemd/system/
sudo systemctl enable --now scraper-bridge
sudo systemctl enable --now scraper-worker@{1..4}
```

## Status

Session 1 · Step 1.1 in progress.
