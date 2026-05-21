"""Shared pytest fixtures for the Chimera test suite.

These fixtures isolate filesystem side-effects (results, logs) into pytest's
tmp_path so the dev `storage/results/` and `logs/` directories stay clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect bridge Settings.results_dir / tools_log_path into tmp_path.

    Clears the lru_cache on get_settings() so the new paths take effect, and
    restores the cache state after the test.
    """
    from bridge import config as bridge_config

    results_dir = tmp_path / "results"
    logs_dir = tmp_path / "logs"
    results_dir.mkdir()
    logs_dir.mkdir()

    # Settings fields are pydantic instance attrs (not class attrs), so we
    # override them via env vars — pydantic-settings reads them on construction
    # and they take precedence over scraper.env values.
    monkeypatch.setenv("RESULTS_DIR", str(results_dir))
    monkeypatch.setenv("TOOLS_LOG_PATH", str(logs_dir / "tools.log"))

    bridge_config.get_settings.cache_clear()
    yield bridge_config.get_settings()
    bridge_config.get_settings.cache_clear()
