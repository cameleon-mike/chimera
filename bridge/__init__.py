"""Chimera bridge — FastAPI API exposed to cameleon over HTTP.

The bridge is intentionally thin: it accepts jobs, dispatches to runners,
returns results. All policy (which tool to use, when to escalate, how to
interpret a screenshot) lives in cameleon. Every configurable option here
is discoverable via /capabilities (served from tool_manifest.json).
"""

__version__ = "0.1.0"
