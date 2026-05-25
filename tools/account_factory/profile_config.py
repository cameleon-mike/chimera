"""ProfileConfig dataclass and warmup site catalogues."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

LOCAL_WARMUP_SITES: dict[str, list[str]] = {
    "BE": ["https://www.rtbf.be", "https://www.lesoir.be", "https://www.hln.be", "https://www.immoweb.be"],
    "FR": ["https://www.lemonde.fr", "https://www.lefigaro.fr", "https://www.leboncoin.fr"],
    "DE": ["https://www.spiegel.de", "https://www.heise.de", "https://www.ebay.de"],
    "GB": ["https://www.bbc.co.uk", "https://www.theguardian.com", "https://www.gumtree.com"],
    "NL": ["https://www.nu.nl", "https://www.marktplaats.nl", "https://www.tweakers.net"],
}

COOKIE_COLLECTION_SITES: list[str] = [
    "https://www.google.com",
    "https://www.youtube.com",
    "https://www.facebook.com",
]

SUPPORTED_COUNTRIES = list(LOCAL_WARMUP_SITES.keys())


@dataclass
class ProfileConfig:
    geo_id: str
    proxy_country: str
    profile_id: str = field(default_factory=lambda: f"prof-{uuid.uuid4().hex[:8]}")
    ua_profile_id: str = "chrome127-win"
    extensions: list[str] = field(default_factory=lambda: ["ublock-origin", "honey"])
    active_hours: tuple[int, int] = (8, 22)
    linked_account: dict = field(default_factory=dict)
