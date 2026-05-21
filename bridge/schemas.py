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
    last_24h: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None
