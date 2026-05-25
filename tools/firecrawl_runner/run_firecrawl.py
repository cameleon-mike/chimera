#!/usr/bin/env python3
"""Firecrawl Runner — Chimera tool.

Input  (stdin) : JSON payload
Output (stdout): JSON result
Exit codes:
  0  success
  2  validation error (missing/invalid url)
  3  runtime error (unhandled exception; process crashed)

Payload fields:
  url               str   required  Target URL
  job_id            str   optional  Generated if absent
  mode              str   optional  "scrape" (default) | "crawl"
  formats           list  optional  ["markdown"] (default); also "html", "rawHtml", "links"
  only_main_content bool  optional  Strip nav/footer boilerplate (default: true)
  wait_ms           int   optional  Extra wait before capture in ms (default: 0)
  timeout_ms        int   optional  HTTP request timeout in ms (default: 30000)
  max_pages         int   optional  (crawl) Page limit (default: 10)
  max_depth         int   optional  (crawl) Link depth limit (default: 2)
  poll_timeout_s    int   optional  (crawl) Max seconds to poll for completion (default: 120)
  mobile            bool  optional  Emulate mobile viewport (default: false)
  headers           dict  optional  Extra HTTP headers sent to the target page (default: {})
  firecrawl_url     str   optional  Firecrawl API base URL
                                    (default: $FIRECRAWL_URL or http://127.0.0.1:3002)
  firecrawl_api_key str   optional  Bearer API key
                                    (default: $FIRECRAWL_API_KEY or "chimera-local")
  proxy             str   optional  Informational — stored in result for traceability
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx

_DEFAULT_FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://127.0.0.1:3002")
_DEFAULT_API_KEY = os.getenv("FIRECRAWL_API_KEY", "chimera-local")


def _auth_headers(api_key: str) -> dict[str, str]:
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _scrape(client: httpx.Client, base_url: str, api_key: str, payload: dict) -> dict:
    url = payload["url"]
    formats = payload.get("formats", ["markdown"])
    only_main = payload.get("only_main_content", True)
    wait_ms = int(payload.get("wait_ms", 0))
    mobile = bool(payload.get("mobile", False))
    req_headers = payload.get("headers") or {}
    timeout_ms = int(payload.get("timeout_ms", 30000))

    body: dict = {
        "url": url,
        "formats": formats,
        "onlyMainContent": only_main,
    }
    if wait_ms:
        body["waitFor"] = wait_ms
    if mobile:
        body["mobile"] = True
    if req_headers:
        body["headers"] = req_headers

    resp = client.post(
        f"{base_url}/v1/scrape",
        json=body,
        headers=_auth_headers(api_key),
        timeout=timeout_ms / 1000.0,
    )
    resp.raise_for_status()
    data = resp.json()

    doc = data.get("data") or {}
    meta = doc.get("metadata") or {}
    http_status = meta.get("statusCode") or resp.status_code
    title = meta.get("title", "")
    md = doc.get("markdown") or ""
    html = doc.get("html") or ""

    out: dict = {
        "tool": "firecrawl",
        "mode": "scrape",
        "url": url,
        "http_status": int(http_status),
        "success": bool(data.get("success", True)),
        "title": title,
        "firecrawl_url": base_url,
    }
    if "markdown" in formats:
        out["markdown"] = md
        out["markdown_len"] = len(md)
    if "html" in formats:
        out["html"] = html
        out["html_len"] = len(html)
    if not out["success"]:
        out["error"] = data.get("error", "firecrawl returned success=false")

    return out


def _crawl(client: httpx.Client, base_url: str, api_key: str, payload: dict) -> dict:
    url = payload["url"]
    formats = payload.get("formats", ["markdown"])
    only_main = payload.get("only_main_content", True)
    wait_ms = int(payload.get("wait_ms", 0))
    max_pages = int(payload.get("max_pages", 10))
    max_depth = int(payload.get("max_depth", 2))
    poll_timeout_s = int(payload.get("poll_timeout_s", 120))
    timeout_ms = int(payload.get("timeout_ms", 30000))

    scrape_opts: dict = {
        "formats": formats,
        "onlyMainContent": only_main,
    }
    if wait_ms:
        scrape_opts["waitFor"] = wait_ms

    body = {
        "url": url,
        "limit": max_pages,
        "maxDepth": max_depth,
        "scrapeOptions": scrape_opts,
    }

    resp = client.post(
        f"{base_url}/v1/crawl",
        json=body,
        headers=_auth_headers(api_key),
        timeout=timeout_ms / 1000.0,
    )
    resp.raise_for_status()
    crawl_id = resp.json()["id"]

    status_data: dict = {}
    deadline = time.monotonic() + poll_timeout_s
    while time.monotonic() < deadline:
        status_resp = client.get(
            f"{base_url}/v1/crawl/{crawl_id}",
            headers=_auth_headers(api_key),
            timeout=30.0,
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()
        crawl_status = status_data.get("status", "")
        if crawl_status == "completed":
            break
        if crawl_status == "failed":
            raise RuntimeError(
                f"Firecrawl crawl {crawl_id} failed: {status_data.get('error', 'unknown')}"
            )
        time.sleep(2)
    else:
        raise RuntimeError(
            f"Firecrawl crawl {crawl_id} did not complete within {poll_timeout_s}s"
        )

    pages = []
    for page in status_data.get("data") or []:
        meta = page.get("metadata") or {}
        pages.append({
            "url": meta.get("sourceURL", ""),
            "title": meta.get("title", ""),
            "http_status": int(meta.get("statusCode") or 200),
            "markdown": page.get("markdown") or "",
            "markdown_len": len(page.get("markdown") or ""),
        })

    return {
        "tool": "firecrawl",
        "mode": "crawl",
        "url": url,
        "crawl_id": crawl_id,
        "http_status": 200,
        "success": True,
        "pages_count": len(pages),
        "pages": pages,
        "firecrawl_url": base_url,
    }


def run(payload: dict) -> dict:
    job_id = payload.get("job_id") or uuid.uuid4().hex[:16]
    url = payload.get("url", "")
    mode = payload.get("mode", "scrape")
    firecrawl_url = (payload.get("firecrawl_url") or _DEFAULT_FIRECRAWL_URL).rstrip("/")
    api_key = payload.get("firecrawl_api_key") or _DEFAULT_API_KEY

    with httpx.Client() as client:
        if mode == "crawl":
            result = _crawl(client, firecrawl_url, api_key, payload)
        else:
            result = _scrape(client, firecrawl_url, api_key, payload)

    result["job_id"] = job_id
    result["proxy"] = payload.get("proxy")
    result["ts"] = datetime.now(timezone.utc).isoformat()
    return result


def main() -> None:
    payload = json.load(sys.stdin)
    if not payload.get("url"):
        print(json.dumps({"error": "missing url"}), file=sys.stderr)
        sys.exit(2)
    try:
        result = run(payload)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(3)
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
