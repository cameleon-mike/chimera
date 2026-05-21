"""CollectorPipeline — accumulates items in memory.

Scrapy's standard FEEDS output writes JSON to disk asynchronously, which is
awkward when we need the items in-process for a CLI tool that returns JSON
to stdout. Instead we collect into a list keyed on the spider, and
`run_scrapy.py` reads `spider._collected_items` after the crawl finishes."""

from __future__ import annotations


class CollectorPipeline:
    def open_spider(self, spider):
        # Spider instance gets a fresh list at start.
        spider._collected_items = []
        spider._final_http_status = None  # set by spiders when they observe a response

    def process_item(self, item, spider):
        # Coerce scrapy.Item → plain dict for JSON serialization.
        if hasattr(item, "items"):
            spider._collected_items.append(dict(item))
        else:
            spider._collected_items.append(item)
        return item
