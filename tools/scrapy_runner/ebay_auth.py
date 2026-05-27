"""EbayTokenManager — OAuth2 client_credentials avec cache en mémoire et rotation de clés."""
from __future__ import annotations

import base64
import time
from datetime import date
from threading import Lock

import requests


class EbayTokenManager:
    DAILY_LIMIT = 4800
    _TOKEN_TTL = 7200  # secondes

    def __init__(self, app_ids: list[str], cert_ids: list[str]) -> None:
        if len(app_ids) != len(cert_ids):
            raise ValueError("app_ids and cert_ids must have the same length")
        self._app_ids = app_ids
        self._cert_ids = cert_ids
        self._tokens: dict[int, dict] = {}  # key_index → {token, expires_at}
        self._calls: dict[int, dict[str, int]] = {}  # key_index → {date_iso: count}
        self._lock: Lock = Lock()

    def get_token(self, key_index: int) -> str:
        # Vérifie le cache hors lock pour éviter deadlock sur HTTP
        cached = self._tokens.get(key_index)
        if cached and cached["expires_at"] > time.time():
            return cached["token"]

        # Cache invalide ou expiré : fetch (peut faire HTTP)
        token = self._fetch_token(key_index)
        with self._lock:
            self._tokens[key_index] = {
                "token": token,
                "expires_at": time.time() + self._TOKEN_TTL,
            }
        return token

    def _fetch_token(self, key_index: int) -> str:
        app_id = self._app_ids[key_index]
        cert_id = self._cert_ids[key_index]
        credentials = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def pick_key(self) -> int:
        today = self._today()
        best_index = 0
        best_count = self._calls.get(0, {}).get(today, 0)

        for i in range(len(self._app_ids)):
            count = self._calls.get(i, {}).get(today, 0)
            if count < best_count:
                best_count = count
                best_index = i

        if best_count >= self.DAILY_LIMIT:
            raise KeyError("all keys exhausted")

        return best_index

    def record_call(self, key_index: int) -> None:
        today = self._today()
        with self._lock:
            if key_index not in self._calls:
                self._calls[key_index] = {}
            self._calls[key_index][today] = self._calls[key_index].get(today, 0) + 1

    def calls_today(self, key_index: int) -> int:
        today = self._today()
        return self._calls.get(key_index, {}).get(today, 0)

    def _today(self) -> str:
        return date.today().isoformat()
