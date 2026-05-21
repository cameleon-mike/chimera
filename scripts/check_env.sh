#!/usr/bin/env bash
# Validate the dev environment for Chimera.
# Exits non-zero if any REQUIRED check fails. Optional checks just warn.

set -uo pipefail

SCRAPER_HOME="${SCRAPER_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$SCRAPER_HOME"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
bold()  { printf "\033[1m%s\033[0m\n" "$*"; }

FAILED=0
WARNED=0

check_required() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    green "  ✓ $label"
  else
    red   "  ✗ $label   (REQUIRED)"
    FAILED=$((FAILED+1))
  fi
}

check_optional() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    green "  ✓ $label"
  else
    yellow "  ⚠ $label   (optional — installed in a later step)"
    WARNED=$((WARNED+1))
  fi
}

bold ""
bold "=== Chimera env check ==="
bold "SCRAPER_HOME = $SCRAPER_HOME"
bold ""

bold "[1/5] System binaries"
check_required "python3  >= 3.11"   bash -c '[[ "$(python3 -c "import sys; print(sys.version_info >= (3,11))")" == "True" ]]'
check_required "node     present"   node --version
check_required "npm      present"   npm --version
check_required "redis-server"       redis-server --version
check_required "redis-cli"          redis-cli --version
check_required "docker   present"   docker --version
check_optional "tesseract (OCR)"    tesseract --version
check_optional "xvfb-run"           which xvfb-run

bold ""
bold "[2/5] Directory layout"
for d in bridge tools network storage logs infra docs scripts tests \
         tools/scrapy_runner tools/firecrawl_runner tools/crawl4ai_runner \
         tools/screenshot_runner tools/waf_bypass \
         network/proxy_pool network/fingerprints \
         storage/results storage/screenshots storage/cookies \
         infra/systemd infra/nginx infra/env; do
  check_required "$d/"               test -d "$SCRAPER_HOME/$d"
done

bold ""
bold "[3/5] Required files"
for f in pyproject.toml Makefile README.md LEGAL.md tool_manifest.json \
         .env.example .gitignore docs/ARCHITECTURE.md docs/ROADMAP.md \
         scripts/redis_dev.sh scripts/check_env.sh; do
  check_required "$f"                test -f "$SCRAPER_HOME/$f"
done

bold ""
bold "[4/5] Python virtualenv (.venv)"
if [[ -d "$SCRAPER_HOME/.venv" ]]; then
  green "  ✓ .venv exists"
  check_optional "fastapi importable"   "$SCRAPER_HOME/.venv/bin/python" -c "import fastapi"
  check_optional "scrapy  importable"   "$SCRAPER_HOME/.venv/bin/python" -c "import scrapy"
  check_optional "rq      importable"   "$SCRAPER_HOME/.venv/bin/python" -c "import rq"
  check_optional "redis   importable"   "$SCRAPER_HOME/.venv/bin/python" -c "import redis"
  check_optional "pydantic importable"  "$SCRAPER_HOME/.venv/bin/python" -c "import pydantic"
  check_optional "structlog importable" "$SCRAPER_HOME/.venv/bin/python" -c "import structlog"
else
  yellow "  ⚠ .venv not found — run 'make install'"
  WARNED=$((WARNED+1))
fi

bold ""
bold "[5/5] Redis liveness"
if redis-cli ping >/dev/null 2>&1; then
  green "  ✓ redis-cli ping → PONG"
else
  yellow "  ⚠ redis not responding — run 'make redis-start'"
  WARNED=$((WARNED+1))
fi

bold ""
bold "=== Summary ==="
if [[ $FAILED -eq 0 ]]; then
  green "All required checks passed. ($WARNED optional warnings)"
  exit 0
else
  red "$FAILED required check(s) failed. ($WARNED optional warnings)"
  exit 1
fi
