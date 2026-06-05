"""ScrapingAgent — automated product scraping cron with APScheduler."""
import logging
import signal
import sys
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class ScrapingAgent:
    """Automated product scraping agent with APScheduler integration."""

    def __init__(
        self,
        base_url: str,
        token: str,
        products: list[str],
        interval_hours: int = 6,
        watchcount_hour: int = 2,
    ):
        """Initialize the ScrapingAgent.

        Args:
            base_url: Base URL of the bridge (e.g., http://127.0.0.1:8080)
            token: Bearer token for authentication
            products: List of product queries to scrape
            interval_hours: Hours between scrape_all jobs (default 6)
            watchcount_hour: Hour of day for watchcount job (default 2)
        """
        self.base_url = base_url
        self.token = token
        self.products = products
        self.interval_hours = interval_hours
        self.watchcount_hour = watchcount_hour
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _scrape_product(self, query: str) -> dict:
        """Scrape a single product across all sources.

        Returns:
            dict with keys: items, epids, median, avg_sell_days
        """
        try:
            # Step 1: Call /aggregate/search with ingest=true
            agg_url = f"{self.base_url}/aggregate/search"
            agg_params = {"q": query, "ingest": "true"}
            agg_resp = requests.get(
                agg_url,
                params=agg_params,
                headers=self._headers,
                timeout=30,
            )
            agg_resp.raise_for_status()
            agg_data = agg_resp.json()

            total_items = agg_data.get("total_items", 0)
            items_list = agg_data.get("items", [])

            # Compute epid coverage
            epid_count = sum(1 for it in items_list if it.get("epid"))
            if total_items > 0 and epid_count / total_items < 0.10:
                coverage_pct = (epid_count / total_items) * 100
                logger.warning(
                    "epid_coverage_low query=%s coverage=%.1f%%",
                    query,
                    coverage_pct,
                )

            # Step 2: Call /watchcount/search
            wc_url = f"{self.base_url}/watchcount/search"
            wc_params = {"q": query}
            wc_resp = requests.get(
                wc_url,
                params=wc_params,
                headers=self._headers,
                timeout=60,
            )
            wc_resp.raise_for_status()
            wc_data = wc_resp.json()

            wc_items = wc_data.get("items", [])
            items_with_end_date = [it for it in wc_items if it.get("end_date")]

            # Step 3: Ingest watchcount items with end_date
            if items_with_end_date:
                ingest_items = []
                for it in items_with_end_date:
                    ingest_item = {
                        "url": it.get("ebay_url"),
                        "epid": None,
                        "title": it.get("title"),
                        "price_value": it.get("price"),
                        "price_currency": "EUR",
                        "start_date": None,
                        "end_date": it.get("end_date"),
                        "source": "watchcount",
                    }
                    ingest_items.append(ingest_item)

                ingest_url = f"{self.base_url}/epid/ingest"
                ingest_payload = {"items": ingest_items, "source": "watchcount"}
                requests.post(
                    ingest_url,
                    json=ingest_payload,
                    headers=self._headers,
                    timeout=30,
                )

            # Step 4: Call /epid/search to get stats
            epid_url = f"{self.base_url}/epid/search"
            epid_params = {"q": query}
            epid_resp = requests.get(
                epid_url,
                params=epid_params,
                headers=self._headers,
                timeout=30,
            )
            epid_resp.raise_for_status()
            epid_data = epid_resp.json()

            median_price = None
            avg_sell_days = None
            if epid_data and len(epid_data) > 0:
                first_epid = epid_data[0]
                median_price = first_epid.get("median_price")
                avg_sell_days = first_epid.get("avg_sell_days")

            return {
                "items": total_items,
                "epids": epid_count,
                "median": median_price,
                "avg_sell_days": avg_sell_days,
            }

        except Exception as exc:
            logger.error("scrape_product error query=%s: %s", query, exc)
            return {
                "items": 0,
                "epids": 0,
                "median": None,
                "avg_sell_days": None,
            }

    def run_once(self, products: Optional[list[str]] = None) -> dict:
        """Run scraping for all products once.

        Args:
            products: Optional list of products to override self.products

        Returns:
            dict mapping product name to result dict
        """
        product_list = products or self.products
        result = {}
        for product in product_list:
            result[product] = self._scrape_product(product)
        logger.info("run_once complete products=%d", len(product_list))
        return result

    def start_scheduler(self) -> None:
        """Start the APScheduler background scheduler.

        Adds two jobs:
        - scrape_all: every N hours at minute 0
        - scrape_watchcount: every day at specified hour
        """
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()

        # Add scrape_all job
        scheduler.add_job(
            self.run_once,
            trigger="cron",
            hour=f"*/{self.interval_hours}",
            minute=0,
            id="scrape_all",
            replace_existing=True,
        )

        # Add scrape_watchcount job
        scheduler.add_job(
            self.run_once,
            trigger="cron",
            hour=self.watchcount_hour,
            minute=0,
            id="scrape_watchcount",
            replace_existing=True,
        )

        # Signal handlers for clean shutdown
        def shutdown_handler(signum, frame):
            logger.info("Received signal %d, shutting down scheduler", signum)
            scheduler.shutdown(wait=False)
            sys.exit(0)

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

        # Start scheduler
        scheduler.start()
        logger.info(
            "APScheduler started — scrape_all every %dh, watchcount at %02d:00",
            self.interval_hours,
            self.watchcount_hour,
        )

        try:
            # Sleep in a loop instead of using float("inf") to avoid OverflowError
            while True:
                time.sleep(3600)  # Sleep 1 hour at a time
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, shutting down")
            scheduler.shutdown(wait=False)
