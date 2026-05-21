# =====================================================================
# Chimera — Makefile
# All commands assume CWD is the repo root.
# Override SCRAPER_HOME on the CLI if running outside the default path.
# =====================================================================

SHELL := /bin/bash
SCRAPER_HOME ?= $(shell pwd)
VENV := $(SCRAPER_HOME)/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Load env from scraper.env if present (don't fail if missing)
-include scraper.env
export

.PHONY: help check-env install venv redis-start redis-stop redis-status \
        start stop logs test reset clean fmt lint manifest-validate

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nChimera targets:\n"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------------------- environment --------------------------------

venv:  ## Create Python 3.11+ virtualenv at .venv
	@if [ ! -d "$(VENV)" ]; then python3 -m venv $(VENV); fi
	@$(PIP) install --quiet --upgrade pip setuptools wheel

install: venv  ## Install all Python deps (incl. dev extras)
	@$(PIP) install --quiet -e ".[dev]"
	@echo "Python deps installed."

check-env:  ## Verify system + Python + Redis + project layout
	@bash scripts/check_env.sh

# ------------------------- redis (dev) --------------------------------

redis-start:  ## Start Redis in background (dev — no systemd)
	@bash scripts/redis_dev.sh start

redis-stop:  ## Stop background Redis
	@bash scripts/redis_dev.sh stop

redis-status:  ## Redis ping
	@redis-cli ping 2>/dev/null || echo "Redis not running"

# ------------------------- runtime ------------------------------------

start: redis-start  ## Start Redis + bridge + 1 RQ worker (dev mode, background)
	@bash scripts/bridge_dev.sh start
	@bash scripts/worker_dev.sh start

stop:  ## Stop bridge + worker (Redis stays up — use redis-stop separately)
	@bash scripts/worker_dev.sh stop
	@bash scripts/bridge_dev.sh stop

bridge-status:  ## Bridge liveness check
	@bash scripts/bridge_dev.sh status

worker-start:  ## Start one RQ worker (high → normal → low priority)
	@bash scripts/worker_dev.sh start

worker-stop:  ## Stop the dev RQ worker
	@bash scripts/worker_dev.sh stop

worker-status:  ## rq info + worker PID
	@bash scripts/worker_dev.sh status

rq-info:  ## RQ queue snapshot
	@.venv/bin/rq info --url "$${REDIS_URL:-redis://127.0.0.1:6379/0}"

logs:  ## Tail all log files
	@tail -F logs/*.log logs/*.jsonl 2>/dev/null || echo "No logs yet"

# ------------------------- quality ------------------------------------

test:  ## Run pytest suite
	@$(PY) -m pytest -q

fmt:  ## Format with ruff
	@$(VENV)/bin/ruff format .

lint:  ## Lint with ruff
	@$(VENV)/bin/ruff check .

manifest-validate:  ## Validate tool_manifest.json against its schema
	@$(PY) scripts/validate_manifest.py

# ------------------------- cleanup ------------------------------------

reset:  ## Clear runtime artifacts (results, screenshots, logs)
	@rm -rf storage/results/* storage/screenshots/* logs/*.log logs/*.jsonl
	@echo "Runtime artifacts cleared."

clean: reset  ## Reset + remove venv
	@rm -rf $(VENV)
	@echo "venv removed."
