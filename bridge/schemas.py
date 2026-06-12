"""Pydantic models for the bridge HTTP API.

ToolName is built **at module load** from `tool_manifest.json`. That makes
the manifest the single source of truth: adding a new tool to the JSON
makes it valid here automatically, and FastAPI's OpenAPI exports the
updated enum to cameleon.

Per-tool `config` payloads stay free-form (`dict[str, Any]`) in this step.
They will be tightened in S2/S3 as each tool lands, with per-tool sub-schemas
generated from the manifest's `params` block.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .manifest import list_tool_names

# --- Enums built from the manifest -----------------------------------

ToolName = Enum(
    "ToolName",
    {name: name for name in list_tool_names()},
    type=str,
)
"""Valid `tool` values for /run-tool. Derived from tool_manifest.json::tools."""


class Priority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class JobStatus(str, Enum):
    queued = "queued"
    started = "started"
    finished = "finished"
    failed = "failed"
    not_found = "not_found"


# --- Request / response models ---------------------------------------


class RunToolRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    tool: ToolName = Field(
        ...,
        description="Scraping engine. Valid values come from tool_manifest.json — discoverable via /capabilities.",
    )
    url: str | list[str] = Field(
        ...,
        description="Target URL or list of URLs.",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific config. See manifest.tools[<tool>].params for the schema.",
    )
    priority: Priority = Field(
        default=Priority.normal,
        description="Queue priority (high / normal / low).",
    )
    callback_url: str | None = Field(
        default=None,
        description="Optional webhook fired when the job finishes.",
    )


class RunToolResponse(BaseModel):
    job_id: str = Field(..., description="16-char hex job ID — use with /status/{id} and /result/{id}.")
    status: JobStatus = Field(..., description="Initial status — 'queued' on accept.")


class StatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    tool: str | None = None
    enqueued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(default="ok", description="'ok' if the bridge is responsive.")
    manifest_version: str = Field(..., description="Version of tool_manifest.json the bridge is serving.")
    bridge_version: str = Field(..., description="Bridge package version.")


class RiskResponse(BaseModel):
    domain: str
    window_hours: int = 24
    requests: int = 0
    blocks: int = 0
    captchas: int = 0
    avg_risk: float = 0.0
    max_risk: float = 0.0
    vendors_seen: list[str] = Field(default_factory=list)
    recommendation: str | None = None


class ProbeRecommendation(BaseModel):
    tool: str
    proxy_tier: str
    fingerprint: str


class ProbeResponse(BaseModel):
    domain: str
    probed_at: str
    risk_score: float
    vendors_detected: list[str]
    tls: dict[str, Any]
    features: dict[str, Any]
    indicators: dict[str, int]
    http_status: int
    recommendation: ProbeRecommendation
    cached: bool = False


class EscalateRequest(BaseModel):
    job_id: str = Field(..., description="Job ID to evaluate for escalation.")
    domain: str | None = Field(default=None, description="Domain being scraped (informational).")
    urls: list[str] | None = Field(default=None, description="URLs scraped (informational).")


class EscalateResponse(BaseModel):
    job_id: str
    needed: bool
    reason: str
    suggested_tool: str | None
    vendors_detected: list[str]
    trigger_threshold: float
    avg_risk: float
    max_risk: float
    response_count: int


class ProfileResponse(BaseModel):
    profile_id: str
    geo_id: str
    proxy_country: str
    ua_profile_id: str
    status: str
    age_days: int
    created_at: str | None = None
    last_active: str | None = None
    warmed: bool = False
    cookies_count: int = 0


class ProfileCreateRequest(BaseModel):
    geo_id: str
    proxy_country: str
    count: int = Field(default=1, ge=1, le=10)
    ua_profile_id: str = "chrome127-win"


class FactoryStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    oldest_profile: str | None = None
    newest_profile: str | None = None


class DailyRunResponse(BaseModel):
    created: list[str]
    warmed: list[str]
    aged: list[str]
    recycled: list[str]
    errors: list[str]


class EbayPrice(BaseModel):
    value: float | None = None
    currency: str | None = None


class EbayItem(BaseModel):
    title: str | None = None
    price: EbayPrice | None = None
    epid: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    photo_url: str | None = None
    link: str | None = None


class EbaySearchResponse(BaseModel):
    query: str
    marketplace: str
    total_items: int
    items: list[EbayItem]
    api_calls_used: int
    risk_scores: list[float]
    ts: str


class WatchCountItem(BaseModel):
    title: str | None = None
    watch_count: int | None = None
    end_date: str | None = None
    price: float | None = None
    ebay_url: str | None = None
    ebay_item_id: str | None = None
    source: str = "watchcount"


class WatchCountSearchResponse(BaseModel):
    query: str
    marketplace: str
    total_items: int
    items: list[WatchCountItem]
    tool_used: str
    recaptcha_detected: bool = False
    ts: str


class TwoememainItem(BaseModel):
    title: str | None = None
    price: EbayPrice | None = None  # CSV-compatible avec EbayItem
    start_date: str | None = None   # date de publication
    end_date: str | None = None
    photo_url: str | None = None
    link: str | None = None
    location: str | None = None
    source: str = "2ememain"


class TwoememainSearchResponse(BaseModel):
    query: str
    total_items: int
    items: list[TwoememainItem]
    tool_used: str
    blocked: bool = False
    error: str | None = None
    ts: str


class AggregatedItem(BaseModel):
    title: str | None = None
    price: EbayPrice | None = None
    epid: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    photo_url: str | None = None
    link: str | None = None
    location: str | None = None
    source: str  # "ebay" | "2ememain"


class VintedSearchResponse(BaseModel):
    query: str
    marketplace: str
    total_items: int
    items: list[AggregatedItem]
    blocked: bool = False
    tool_used: str = "scrapy"
    ts: str


class AggregateSearchResponse(BaseModel):
    query: str
    marketplace: str
    total_items: int
    items: list[AggregatedItem]
    sources: dict[str, int]       # {"ebay": N, "2ememain": M}
    duplicates_removed: int
    ebay_blocked: bool = False
    twoememain_blocked: bool = False
    ts: str


class EpidStats(BaseModel):
    epid: str
    brand: str | None = None
    model: str | None = None
    total_items: int = 0
    currency: str | None = None
    median_price: float | None = None
    q1_price: float | None = None
    q2_price: float | None = None
    q3_price: float | None = None
    q4_price: float | None = None
    avg_sell_days: float | None = None
    min_sell_days: float | None = None
    max_sell_days: float | None = None
    sell_days_sample: int = 0
    last_updated: str | None = None


class IngestRequest(BaseModel):
    items: list[dict]
    source: str = "unknown"


class IngestResponse(BaseModel):
    ingested: int
    epids_updated: int


class FlipScoreResponse(BaseModel):
    epid: str
    listed_price: float
    market_median: float | None
    decision: str
    confidence: float
    price_ratio: float | None
    margin_eur: float | None
    margin_pct: float | None
    velocity_flag: str
    reasoning: str


class DealItem(BaseModel):
    epid: str
    title: str | None = None
    listed_price: float
    link: str | None = None
    decision: str
    confidence: float
    price_ratio: float | None = None
    margin_eur: float | None = None
    margin_pct: float | None = None
    velocity_flag: str
    reasoning: str


class DealsResponse(BaseModel):
    query: str
    total_scored: int
    deals_found: int
    deals: list[DealItem]


class NavigatorRunRequest(BaseModel):
    query: str = Field(..., description="Search query")
    max_price: float | None = Field(default=None, description="Maximum price filter in EUR")
    marketplace: str = Field(default="EBAY_FR", description="Marketplace ID")


class NavigatorRunResponse(BaseModel):
    query: str
    pipeline_ms: int
    probe_risk: float
    total_scraped: int
    total_scored: int
    deals: list[dict]
    summary: str


class DashboardResponse(BaseModel):
    bridge: dict
    jobs: dict
    scraping: dict
    scoring: dict
    profiles: dict
    proxy: dict


# --- Stealth (S4) ----------------------------------------------------

class StealthRunRequest(BaseModel):
    url: str
    query: str | None = None
    source: str = "custom"
    config: dict[str, Any] | None = None
    agent_id: str = "manual"


class StealthRunResponse(BaseModel):
    run_id: str
    status: str
    security: dict[str, Any]
    result: dict[str, Any]
    report: dict[str, Any]


class StealthRunSummary(BaseModel):
    run_id: str
    created_at: str | None = None
    url: str
    query: str | None = None
    source: str | None = None
    status: str | None = None
    http_status: int | None = None
    items_count: int | None = None
    duration_ms: int | None = None


class StealthStatusResponse(BaseModel):
    run_id: str
    status: str
    phase: str | None = None
    elapsed_ms: int | None = None
