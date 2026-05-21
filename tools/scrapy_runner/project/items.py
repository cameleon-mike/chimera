"""Minimal item model. Spiders are free to use scrapy.Item OR raw dicts —
the CollectorPipeline accepts both. This file documents the canonical
shape for adaptive spiders."""

import scrapy


class ScrapedItem(scrapy.Item):
    url = scrapy.Field()
    fetched_at = scrapy.Field()  # ISO8601 UTC
    data = scrapy.Field()        # arbitrary payload dict
