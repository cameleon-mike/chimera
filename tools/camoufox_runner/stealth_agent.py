#!/usr/bin/env python3
"""StealthAgent — Chimera Stealth orchestrator (Step S3).

Runs the full 5-phase stealth pipeline in a single ``run()`` call:

  Phase 1  scan security      → ScanSecurity.scan(url)
  Phase 2  configure Camoufox → proxy_country / wait_ms from security_map
  Phase 3  fetch              → CamoufoxRunner.fetch(url, wait_ms)
  Phase 4  extract            → UniversalExtractor.extract(html, markdown)
  Phase 5  persist + report   → stealth_runs row + CSV/JSON report (+ optional ingest)

Contract: ``run()`` NEVER raises. It always returns a structured dict, always
updates the stealth_runs row, and always writes a report (even with items=[]).
"""
from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Source → extraction schema. Add new marketplaces here.
_SCHEMA_BY_SOURCE = {
    "vinted": Path(__file__).parent.parent / "extractors" / "schemas" / "vinted_fr.json",
}

_STEALTH_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS stealth_runs (
    run_id          TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    url             TEXT NOT NULL,
    query           TEXT,
    source          TEXT,
    status          TEXT DEFAULT 'running',
    duration_ms     INTEGER,
    security_map    TEXT,
    config_used     TEXT,
    http_status     INTEGER,
    html_len        INTEGER,
    items_count     INTEGER DEFAULT 0,
    items_json      TEXT,
    raw_markdown    TEXT,
    report_path     TEXT,
    error_msg       TEXT,
    agent_id        TEXT,
    ingest_done     INTEGER DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StealthAgent:
    """Orchestrates scan → configure → fetch → extract → persist."""

    def __init__(self, settings, db_path: str):
        self.settings = settings
        self.db_path = str(db_path)
        # Anchored to the repo root (not CWD) so reports land correctly under
        # systemd/other working dirs. Overridable in tests to use tmp_path.
        self.reports_dir = Path(__file__).resolve().parents[2] / "storage" / "stealth_reports"
        self._ensure_schema()

    # -- public ------------------------------------------------------------

    def run(
        self,
        url: str,
        query: str | None = None,
        source: str = "custom",
        config: dict | None = None,
        agent_id: str = "manual",
    ) -> dict:
        config = config or {}
        run_id = "sr-" + uuid.uuid4().hex[:8]
        started = datetime.now(timezone.utc)

        # Defaults so an early failure still yields a structured response.
        security_map: dict = {}
        fetch_result: dict = {}
        items: list = []
        status = "running"
        error_msg = None

        self._insert_run(run_id, url, query, source, config, agent_id)

        try:
            # Phase 1 — scan
            security_map = self._phase1_scan(url)
            self._update(run_id, security_map=json.dumps(security_map, default=str))

            # Phase 2 — configure
            camoufox_config = self._phase2_configure(security_map, config)

            # Phase 3 — fetch
            fetch_result = self._phase3_fetch(url, camoufox_config)
            http_status = int(fetch_result.get("http_status") or 0)
            html = fetch_result.get("html", "") or ""
            markdown = fetch_result.get("markdown", "") or ""
            self._update(
                run_id,
                http_status=http_status,
                html_len=fetch_result.get("html_len", len(html)),
                raw_markdown=markdown[:200_000],
            )

            if fetch_result.get("error") or http_status != 200:
                status = "error"
                error_msg = fetch_result.get("error") or f"http_status={http_status}"
            elif "captcha" in markdown.lower() or "captcha" in html[:5000].lower():
                status = "captcha_blocked"
            else:
                status = "success"

            # Phase 4 — extract (only meaningful with content; safe otherwise)
            if status != "error":
                items = self._phase4_extract(html, markdown, source)
                items = self._score_items(items)

        except Exception as exc:  # never propagate
            status = "error"
            error_msg = self._scrub(str(exc))

        # Phase 5 — persist + report (ALWAYS runs)
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        try:
            report = self._phase5_persist(
                run_id,
                {
                    "url": url,
                    "query": query,
                    "source": source,
                    "config": config,
                    "status": status,
                    "error_msg": error_msg,
                    "security_map": security_map,
                    "fetch_result": fetch_result,
                    "items": items,
                    "duration_ms": duration_ms,
                },
            )
        except Exception as exc:
            # Persist failure must not lose the original phase 1-4 error context.
            report = {"json_path": None, "csv_path": None}
            combined = "; ".join(filter(None, [error_msg, f"persist_failed: {exc}"]))
            self._update(run_id, status=status, error_msg=self._scrub(combined))

        return {
            "run_id": run_id,
            "status": status,
            "security": {
                "waf": security_map.get("waf"),
                "captcha": bool(security_map.get("captcha", False)),
                "difficulty": security_map.get("difficulty", 0),
            },
            "result": {
                "http_status": int(fetch_result.get("http_status") or 0),
                "html_len": int(fetch_result.get("html_len") or 0),
                "items_count": len(items),
                "duration_ms": duration_ms,
            },
            "report": {
                "json_url": report.get("json_path"),
                "csv_url": report.get("csv_path"),
            },
        }

    # -- phases ------------------------------------------------------------

    def _phase1_scan(self, url: str) -> dict:
        from tools.camoufox_runner.scan_security import ScanSecurity

        return ScanSecurity(self.settings).scan(url)

    def _phase2_configure(self, security_map: dict, config: dict) -> dict:
        wait_ms = int(config.get("wait_ms", 4000))
        if int(security_map.get("difficulty", 0) or 0) > 6:
            wait_ms += 2000
        return {
            "proxy_country": config.get("proxy_country", "BE"),
            "wait_ms": wait_ms,
        }

    def _phase3_fetch(self, url: str, camoufox_config: dict) -> dict:
        from tools.camoufox_runner.run_camoufox import CamoufoxRunner

        country = camoufox_config.get("proxy_country")
        proxy_config = {"country": country} if country else None
        runner = CamoufoxRunner(proxy_config=proxy_config)
        return runner.fetch(url, wait_ms=camoufox_config.get("wait_ms", 4000))

    def _phase4_extract(self, html: str, markdown: str, source: str) -> list:
        schema_path = _SCHEMA_BY_SOURCE.get(source)
        if schema_path is None or not Path(schema_path).exists():
            return []
        try:
            from tools.extractors.universal_extractor import UniversalExtractor

            extractor = UniversalExtractor(
                schema_path=str(schema_path),
                groq_api_key=getattr(self.settings, "groq_api_key", "") or "",
            )
            return extractor.extract(html or "", markdown or "")
        except Exception:
            return []

    def _phase5_persist(self, run_id: str, all_data: dict) -> dict:
        items = all_data.get("items") or []
        config = all_data.get("config") or {}

        report = self._generate_report(run_id, items, meta=all_data)

        ingest_done = 0
        if config.get("ingest"):
            ingest_done = self._ingest(items)

        self._update(
            run_id,
            status=all_data.get("status"),
            duration_ms=all_data.get("duration_ms"),
            config_used=json.dumps(config, default=str),
            items_count=len(items),
            items_json=json.dumps(items, default=str),
            report_path=report.get("json_path"),
            error_msg=all_data.get("error_msg"),
            ingest_done=ingest_done,
        )
        return report

    # -- helpers -----------------------------------------------------------

    def _generate_report(self, run_id: str, items: list, meta: dict | None = None) -> dict:
        meta = meta or {}
        run_dir = self.reports_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        json_path = run_dir / "report.json"
        csv_path = run_dir / "report.csv"
        source = meta.get("source", "custom")

        # CSV: title, price_eur, source, url, decision, confidence
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["title", "price_eur", "source", "url", "decision", "confidence"])
            for it in items:
                writer.writerow([
                    it.get("title"),
                    it.get("price_eur"),
                    source,
                    it.get("url"),
                    it.get("decision"),
                    it.get("confidence"),
                ])

        # JSON: full run + items
        payload = {
            "run_id": run_id,
            "status": meta.get("status"),
            "url": meta.get("url"),
            "query": meta.get("query"),
            "source": source,
            "security": meta.get("security_map", {}),
            "result": {
                "http_status": (meta.get("fetch_result") or {}).get("http_status"),
                "html_len": (meta.get("fetch_result") or {}).get("html_len"),
                "items_count": len(items),
                "duration_ms": meta.get("duration_ms"),
            },
            "items": items,
            "generated_at": _now(),
        }
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str, indent=2)

        return {"json_path": str(json_path), "csv_path": str(csv_path)}

    def _score_items(self, items: list) -> list:
        if not items:
            return items
        try:
            from tools.decision_agent.scorer import FlipScorer
        except Exception:
            return items

        scorer = FlipScorer()
        conn = sqlite3.connect(self.db_path)
        try:
            enriched = []
            for item in items:
                epid = item.get("epid")
                price = item.get("price_eur")
                if epid and isinstance(price, (int, float)) and price > 0:
                    stats = self._fetch_epid_stats(conn, epid)
                    if stats:
                        try:
                            s = scorer.score(price, stats)
                            item = {**item, "decision": s["decision"],
                                    "confidence": s["confidence"]}
                        except Exception:
                            pass
                enriched.append(item)
            return enriched
        finally:
            conn.close()

    def _fetch_epid_stats(self, conn: sqlite3.Connection, epid: str) -> dict | None:
        try:
            cur = conn.execute(
                """
                SELECT epid, brand, model, total_items, currency,
                       median_price, q1_price, q2_price, q3_price, q4_price,
                       avg_sell_days, min_sell_days, max_sell_days, sell_days_sample,
                       last_updated
                FROM epid_stats WHERE epid = ?
                """,
                (epid,),
            )
            row = cur.fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        cols = ["epid", "brand", "model", "total_items", "currency", "median_price",
                "q1_price", "q2_price", "q3_price", "q4_price", "avg_sell_days",
                "min_sell_days", "max_sell_days", "sell_days_sample", "last_updated"]
        return dict(zip(cols, row))

    def _ingest(self, items: list) -> int:
        """Group items by epid and upsert epid_stats. Best-effort; never raises."""
        by_epid: dict[str, list] = {}
        for it in items:
            epid = it.get("epid")
            if epid:
                by_epid.setdefault(epid, []).append(it)
        if not by_epid:
            return 0
        try:
            from tools.stats.epid_calculator import upsert_epid_stats

            conn = sqlite3.connect(self.db_path)
            try:
                for epid, group in by_epid.items():
                    upsert_epid_stats(conn, epid, group)
                conn.commit()
            finally:
                conn.close()
            return 1
        except Exception:
            return 0

    # -- db ----------------------------------------------------------------

    def _ensure_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(_STEALTH_RUNS_DDL)
            conn.commit()
        finally:
            conn.close()

    def _insert_run(self, run_id, url, query, source, config, agent_id) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO stealth_runs
                    (run_id, created_at, url, query, source, status, config_used, agent_id)
                VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (run_id, _now(), url, query, source,
                 json.dumps(config or {}, default=str), agent_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _update(self, run_id: str, **fields) -> None:
        # NOTE: column names come from **fields keys, which are always internal
        # source-literal kwargs (never user input). Values are parameterized.
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [run_id]
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(f"UPDATE stealth_runs SET {cols} WHERE run_id = ?", params)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _scrub(msg: str) -> str:
        """Best-effort removal of any proxy password from an error string."""
        try:
            from bridge.config import get_settings

            pw = get_settings().brightdata_password
            if pw:
                return msg.replace(pw, "***")
        except Exception:
            pass
        return msg
