"""Security probe: HTTP headers + TLS + vendor fingerprinting. No browser."""
from __future__ import annotations

import socket
import ssl
import urllib.request
from datetime import UTC, datetime
from typing import Any

from tools.probe.scoring import compute_risk_score


def _probe_tls(domain: str) -> dict[str, Any]:
    """Attempt TLS handshake and return version/cipher/has_cert."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=5) as raw_sock:
            with ctx.wrap_socket(raw_sock, server_hostname=domain) as tls_sock:
                version = tls_sock.version() or "unknown"
                cipher_info = tls_sock.cipher()
                cipher_name = cipher_info[0] if cipher_info else "unknown"
                return {"version": version, "cipher": cipher_name, "has_cert": True}
    except Exception:
        return {"version": "unknown", "cipher": "unknown", "has_cert": False}


def _detect_vendors(headers_str: str, body_snippet: str) -> list[str]:
    """Return list of detected vendor names from combined header+body text."""
    combined = headers_str.lower() + body_snippet.lower()
    headers_lower = headers_str.lower()

    detected = []

    # cloudflare
    if (
        "cf-ray:" in headers_lower
        or "cloudflare" in headers_lower
        or "__cf_chl_" in combined
        or "cf-mitigated" in headers_lower
    ):
        detected.append("cloudflare")

    # akamai
    if "_abck" in headers_lower or "akamai-bot" in headers_lower:
        detected.append("akamai")

    # perimeterx
    if "px-captcha" in combined or "_px3" in combined:
        detected.append("perimeterx")

    # datadome
    if "datadome" in combined or "dd-protected" in combined:
        detected.append("datadome")

    # imperva
    if "_incap_ses" in headers_lower or "incapsula" in combined:
        detected.append("imperva")

    # sucuri
    if "sucuri" in combined:
        detected.append("sucuri")

    return detected


def _detect_captcha(combined: str) -> bool:
    combined_lower = combined.lower()
    return any(
        indicator in combined_lower
        for indicator in ("g-recaptcha", "hcaptcha", "turnstile")
    )


def _detect_botdet(combined: str) -> bool:
    combined_lower = combined.lower()
    return any(
        indicator in combined_lower
        for indicator in ("fpjs", "fingerprintjs", "botdetect")
    )


def _extract_header(headers_map: Any, name: str) -> str | None:
    """Extract a header value case-insensitively."""
    try:
        val = headers_map.get(name)
        return val if val else None
    except Exception:
        return None


def probe_domain(domain: str) -> dict[str, Any]:
    """Probe a domain and return the normalized JSON result dict.

    Performs:
    - HEAD + GET request (httplib/urllib, no third-party HTTP lib)
    - TLS inspection via ssl module
    - Vendor/indicator detection in headers + body snippet (first 8KB)
    - Security header extraction
    - risk_score computation via scoring.compute_risk_score

    Total timeout: hard-cap 15 seconds global (TD-13).
    Returns normalized dict matching ProbeResponse schema.
    """
    probed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    _zero_result: dict[str, Any] = {
        "domain": domain,
        "probed_at": probed_at,
        "risk_score": 0.0,
        "vendors_detected": [],
        "tls": {"version": "unknown", "cipher": "unknown", "has_cert": False},
        "features": {
            "hsts": None,
            "csp": None,
            "x_frame_options": None,
            "permissions_policy": None,
        },
        "indicators": {"waf": 0, "captcha": 0, "botdet": 0},
        "http_status": 0,
        "recommendation": {
            "tool": "scrapy",
            "proxy_tier": "datacenter",
            "fingerprint": "chrome127-win",
        },
        "timeout": False,
    }

    def _inner() -> dict[str, Any]:
        try:
            url = f"https://{domain}/"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/127.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )

            http_status = 0
            headers_str = ""
            headers_dict: dict[str, str] = {}
            body_snippet = ""

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    http_status = resp.status
                    raw_headers = resp.headers
                    if isinstance(raw_headers, dict):
                        headers_dict = {k.lower(): v for k, v in raw_headers.items()}
                        headers_str = "\n".join(f"{k}: {v}" for k, v in raw_headers.items())
                    else:
                        headers_str = str(raw_headers)
                        headers_dict = {
                            k.lower(): v
                            for k, v in (
                                (line.split(":", 1)[0].strip(), line.split(":", 1)[1].strip())
                                for line in headers_str.splitlines()
                                if ":" in line
                            )
                        }
                    raw_body = resp.read(8192)
                    body_snippet = raw_body.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                http_status = exc.code
                raw_headers = exc.headers
                if raw_headers:
                    if isinstance(raw_headers, dict):
                        headers_dict = {k.lower(): v for k, v in raw_headers.items()}
                        headers_str = "\n".join(f"{k}: {v}" for k, v in raw_headers.items())
                    else:
                        headers_str = str(raw_headers)
                        headers_dict = {
                            k.lower(): v
                            for k, v in (
                                (line.split(":", 1)[0].strip(), line.split(":", 1)[1].strip())
                                for line in headers_str.splitlines()
                                if ":" in line
                            )
                        }
                try:
                    raw_body = exc.read(8192)
                    body_snippet = raw_body.decode("utf-8", errors="replace")
                except Exception:
                    body_snippet = ""

            combined = headers_str + body_snippet

            vendors_detected = _detect_vendors(headers_str, body_snippet)
            captcha_detected = _detect_captcha(combined)
            botdet_detected = _detect_botdet(combined)

            def _get_header_value(header_name: str) -> str | None:
                # First try the parsed dict
                val = headers_dict.get(header_name.lower())
                if val:
                    return val
                # Fall back to line scan of headers_str
                for line in headers_str.splitlines():
                    if line.lower().startswith(header_name.lower() + ":"):
                        return line[len(header_name) + 1:].strip()
                return None

            hsts_value = _get_header_value("strict-transport-security")
            csp_value = _get_header_value("content-security-policy")
            x_frame_value = _get_header_value("x-frame-options")
            permissions_policy_value = _get_header_value("permissions-policy")

            # Evaluate strict flags
            hsts_strict = False
            if hsts_value:
                for part in hsts_value.split(";"):
                    part = part.strip()
                    if part.lower().startswith("max-age="):
                        try:
                            max_age = int(part.split("=", 1)[1])
                            if max_age > 31536000:
                                hsts_strict = True
                        except (ValueError, IndexError):
                            pass

            csp_strict = bool(csp_value and "default-src 'self'" in csp_value)
            x_frame_deny = bool(
                x_frame_value and x_frame_value.upper() in {"DENY", "SAMEORIGIN"}
            )

            scoring_features = {
                "vendors_detected": vendors_detected,
                "captcha_detected": captcha_detected,
                "botdet_detected": botdet_detected,
                "hsts_strict": hsts_strict,
                "csp_strict": csp_strict,
                "x_frame_deny": x_frame_deny,
                "http_status": http_status,
            }

            risk_score, recommendation = compute_risk_score(scoring_features)

            tls_info = _probe_tls(domain)

            return {
                "domain": domain,
                "probed_at": probed_at,
                "risk_score": risk_score,
                "vendors_detected": vendors_detected,
                "tls": tls_info,
                "features": {
                    "hsts": hsts_value,
                    "csp": csp_value,
                    "x_frame_options": x_frame_value,
                    "permissions_policy": permissions_policy_value,
                },
                "indicators": {
                    "waf": len(vendors_detected),
                    "captcha": 1 if captcha_detected else 0,
                    "botdet": 1 if botdet_detected else 0,
                },
                "http_status": http_status,
                "recommendation": recommendation,
                "timeout": False,
            }

        except Exception:
            return _zero_result

    import concurrent.futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = ex.submit(_inner)
    ex.shutdown(wait=False)
    try:
        return future.result(timeout=15)
    except concurrent.futures.TimeoutError:
        _zero_result["timeout"] = True
        _zero_result["risk_score"] = None
        return _zero_result
    except Exception:
        return _zero_result
