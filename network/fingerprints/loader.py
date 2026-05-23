from __future__ import annotations
import json
import random
from pathlib import Path


_DEFAULT_DIR = Path(__file__).parent


class FingerprintLoader:
    def __init__(self, fingerprints_dir: Path | str | None = None):
        d = Path(fingerprints_dir) if fingerprints_dir else _DEFAULT_DIR
        self._ua_pool = json.loads((d / "ua_pool.json").read_text())["profiles"]
        self._headers = json.loads((d / "headers_pool.json").read_text())["by_profile_id"]
        self._geo = json.loads((d / "geo_profiles.json").read_text())

    def pick_coherent(self, geo_id: str | None = None) -> dict:
        """Return a complete coherent fingerprint dict.

        Returns:
            {
              "profile_id": str,
              "ua": str,
              "headers": dict (header_name -> value, sans User-Agent),
              "header_order": list[str],
              "viewport": [int, int],
              "locale": str | None,
              "timezone": str | None,
              "proxy_country": str | None,
            }
        """
        if geo_id and geo_id in self._geo:
            geo = self._geo[geo_id]
            compatible = geo.get("compatible_ua_profiles", [])
            candidates = [p for p in self._ua_pool if p["id"] in compatible]
            profile = random.choice(candidates) if candidates else random.choice(self._ua_pool)
            locale = geo.get("locale")
            timezone = geo.get("timezone")
            proxy_country = geo.get("proxy_country")
            accept_lang = geo.get("accept_language")
        else:
            profile = random.choice(self._ua_pool)
            locale = None
            timezone = None
            proxy_country = None
            accept_lang = None

        pid = profile["id"]
        headers_entry = self._headers.get(pid, {})
        order = headers_entry.get("_order", [])
        headers = {k: v for k, v in headers_entry.items() if not k.startswith("_")}

        # Override Accept-Language with geo's if provided
        if accept_lang and "Accept-Language" in headers:
            headers["Accept-Language"] = accept_lang

        viewport = random.choice(profile.get("viewport_options") or [[1920, 1080]])

        return {
            "profile_id": pid,
            "ua": profile["ua"],
            "headers": headers,
            "header_order": order,
            "viewport": viewport,
            "locale": locale,
            "timezone": timezone,
            "proxy_country": proxy_country,
        }

    def get_profile(self, profile_id: str) -> dict | None:
        for p in self._ua_pool:
            if p["id"] == profile_id:
                return p
        return None

    def validate_pool(self) -> list[str]:
        """Return list of coherence errors. Empty list = valid pool."""
        errors = []
        profile_ids = {p["id"] for p in self._ua_pool}

        BOT_SIGNALS = {"selenium", "headlesschrome", "phantomjs", "headless", "webdriver", "bot"}

        for p in self._ua_pool:
            pid = p["id"]
            ua_lower = p.get("ua", "").lower()

            # Check bot signals in UA
            for sig in BOT_SIGNALS:
                if sig in ua_lower:
                    errors.append(f"{pid}: UA contains bot signal '{sig}'")

            # Chrome profile must have sec_ch_ua consistent
            browser = p.get("browser", "")
            sec_ch = p.get("sec_ch_ua") or ""
            if browser == "chrome" and sec_ch and "Firefox" in sec_ch:
                errors.append(f"{pid}: Chrome profile has Firefox in sec_ch_ua")
            if browser == "firefox" and sec_ch and "Google Chrome" in sec_ch:
                errors.append(f"{pid}: Firefox profile has Google Chrome in sec_ch_ua")

            # Viewport sanity
            viewports = p.get("viewport_options") or []
            if not viewports:
                errors.append(f"{pid}: viewport_options is empty")
            for vp in viewports:
                if len(vp) != 2 or vp[0] < 320 or vp[1] < 240:
                    errors.append(f"{pid}: unrealistic viewport {vp}")

            # Check sec_ch_ua bot signals
            for sig in BOT_SIGNALS:
                if sig in sec_ch.lower():
                    errors.append(f"{pid}: sec_ch_ua contains bot signal '{sig}'")

        # Check headers_pool _order consistency
        for pid, entry in self._headers.items():
            order = entry.get("_order", [])
            available = {k for k in entry if not k.startswith("_")}
            for h in order:
                if h not in available:
                    errors.append(f"{pid}: _order lists '{h}' but header not present")

            # Check bot signals in header values
            for k, v in entry.items():
                if k.startswith("_"):
                    continue
                v_lower = str(v).lower()
                for sig in BOT_SIGNALS:
                    if sig in v_lower:
                        errors.append(f"{pid}: header '{k}' contains bot signal '{sig}'")

        # Check geo profiles
        for geo_id, geo in self._geo.items():
            for ref_pid in geo.get("compatible_ua_profiles", []):
                if ref_pid not in profile_ids:
                    errors.append(f"geo {geo_id}: compatible_ua_profiles references unknown profile '{ref_pid}'")

            # Accept-Language coherence with locale
            geo_lang = geo.get("accept_language", "")
            geo_locale = geo.get("locale", "")
            if geo_locale and geo_lang:
                lang_prefix = geo_locale.split("-")[0]
                if lang_prefix not in geo_lang:
                    errors.append(f"geo {geo_id}: accept_language '{geo_lang}' inconsistent with locale '{geo_locale}'")

        return errors
