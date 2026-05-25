#!/usr/bin/env python3
import sys, json, uuid, httpx
from datetime import datetime, timezone

FLARESOLVERR_URL = "http://127.0.0.1:8191/v1"

def main():
    payload = json.load(sys.stdin)
    url = payload.get("url", "")
    if not url:
        print(json.dumps({"error": "missing url"}), file=sys.stderr)
        sys.exit(2)

    job_id = payload.get("job_id") or str(uuid.uuid4())
    flaresolverr_url = payload.get("flaresolverr_url", FLARESOLVERR_URL)
    session_id = payload.get("session_id")
    max_timeout = payload.get("max_timeout", 60000)

    try:
        # httpx timeout (120s) > max_timeout/1000 (60s default) so the HTTP
        # layer never cuts the connection before FlareSolverr finishes solving.
        with httpx.Client(timeout=120) as client:
            body = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": max_timeout,
            }
            if session_id:
                body["session"] = session_id

            r = client.post(flaresolverr_url, json=body)
            data = r.json()

        solution = data.get("solution", {})
        result = {
            "job_id":       job_id,
            "tool":         "bypass_waf",
            "url":          url,
            "final_url":    solution.get("url", url),
            "http_status":  solution.get("status", 0),
            "html":         solution.get("response", ""),
            "html_len":     len(solution.get("response", "")),
            "cookies":      solution.get("cookies", []),
            "cf_clearance": next(
                (c["value"] for c in solution.get("cookies", [])
                 if c.get("name") == "cf_clearance"), None
            ),
            "user_agent":   solution.get("userAgent", ""),
            "flaresolverr_status": data.get("status", "unknown"),
            "ts":           datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(result, default=str))

    except httpx.ConnectError:
        print(json.dumps({
            "job_id": job_id, "tool": "bypass_waf",
            "error": "FlareSolverr not running on " + flaresolverr_url,
            "suggestion": "docker compose -f infra/docker/docker-compose.flaresolverr.yml up -d"
        }), file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(json.dumps({"job_id": job_id, "error": str(e)}), file=sys.stderr)
        sys.exit(3)

if __name__ == "__main__":
    main()
