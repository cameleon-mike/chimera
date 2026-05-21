"""Log-normal jitter on top of Scrapy's DOWNLOAD_DELAY.

Architecture doc §6.4 — constant delays are a fingerprint. We add a small
log-normal multiplier so consecutive requests don't look mechanical.
The middleware is intentionally light: AutoThrottle still does the heavy
lifting on actual response timing."""

from __future__ import annotations

import math
import random
import time


class HumanDelayMiddleware:
    def __init__(self, mean: float = 0.4, jitter: float = 0.5):
        self.mean = mean
        self.jitter = jitter

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        return cls(
            mean=s.getfloat("HUMAN_DELAY_MEAN", 0.4),
            jitter=s.getfloat("HUMAN_DELAY_JITTER", 0.5),
        )

    def process_request(self, request, spider):
        # Cap at 4s to avoid pathological tails.
        delay = min(4.0, max(0.0, random.lognormvariate(math.log(max(0.05, self.mean)), self.jitter)))
        time.sleep(delay)
        return None
