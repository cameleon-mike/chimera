"""Pydantic-settings loader. Values come from `scraper.env` at the repo root.

The repo root is resolved relative to this file so the bridge works whether
SCRAPER_HOME is /workspaces/chimera (dev) or /opt/scraper-pack (prod).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "scraper.env"


def _abs(p: str | Path) -> Path:
    """Resolve a path relative to the repo root if it is not absolute."""
    p = Path(p)
    return p if p.is_absolute() else REPO_ROOT / p


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    scraper_home: Path = Field(default=REPO_ROOT, description="Project root.")

    # --- Bridge -------------------------------------------------------
    bridge_host: str = Field(default="127.0.0.1", description="Bind address for uvicorn.")
    bridge_port: int = Field(default=8080, description="Bind port for uvicorn.")
    bridge_workers: int = Field(default=2, description="uvicorn worker count.")
    bridge_auth_token: str = Field(
        ...,
        description="Bearer token required from cameleon on every state-changing call.",
        min_length=32,
    )
    bridge_allowed_ips: str = Field(
        default="127.0.0.1",
        description="Comma-separated IP allowlist (advisory in dev; enforced by nginx in prod).",
    )
    docs_enabled: bool = Field(
        default=True,
        description="Expose /docs, /redoc and /openapi.json. Set false in prod (cameleon uses /capabilities).",
    )

    # --- Redis / RQ ---------------------------------------------------
    redis_url: str = Field(default="redis://127.0.0.1:6379/0")
    rq_queues: str = Field(default="high,normal,low")
    rq_default_timeout: int = Field(default=600)

    # --- Logging ------------------------------------------------------
    log_level: str = Field(default="INFO")
    audit_log_path: Path = Field(default=Path("logs/audit.jsonl"))
    bridge_log_path: Path = Field(default=Path("logs/bridge.log"))
    tools_log_path: Path = Field(default=Path("logs/tools.log"))

    # --- Storage ------------------------------------------------------
    results_dir: Path = Field(default=Path("storage/results"))
    screenshots_dir: Path = Field(default=Path("storage/screenshots"))
    cookies_dir: Path = Field(default=Path("storage/cookies"))
    risk_db_path: Path = Field(default=Path("storage/risk_db.sqlite"))

    # --- Risk thresholds (mirror tool_manifest.json) ------------------
    risk_ok_max: float = 0.2
    risk_suspect_max: float = 0.5
    risk_challenge_max: float = 0.8

    def resolve_paths(self) -> "Settings":
        """Make all path fields absolute under repo root."""
        for name in ("audit_log_path", "bridge_log_path", "tools_log_path",
                     "results_dir", "screenshots_dir", "cookies_dir", "risk_db_path"):
            setattr(self, name, _abs(getattr(self, name)))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings().resolve_paths()
