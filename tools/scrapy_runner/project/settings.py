"""Scrapy settings for the scrapy_runner project.

These are the project-wide defaults. The CLI runner (`run_scrapy.py`) can
override DOWNLOAD_DELAY, USER_AGENT, ROBOTSTXT_OBEY, LOG_LEVEL via the
job config payload — anything not provided falls back to these defaults.
"""

BOT_NAME = "chimera_scrapy"
SPIDER_MODULES = ["tools.scrapy_runner.project.spiders"]
NEWSPIDER_MODULE = "tools.scrapy_runner.project.spiders"

# --- Politeness (architecture doc §3.1) ------------------------------
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 1.0
CONCURRENT_REQUESTS_PER_DOMAIN = 2
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# --- Identity --------------------------------------------------------
# USER_AGENT is set per-request by RotateUserAgentMiddleware.
USER_AGENT = "chimera-scrapy/0.1 (+secondpulse)"

# --- Pipelines & middlewares ----------------------------------------
ITEM_PIPELINES = {
    "tools.scrapy_runner.project.pipelines.CollectorPipeline": 100,
}
DOWNLOADER_MIDDLEWARES = {
    # Disable Scrapy's stock UA middleware so ours is the only voice.
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    # RotateUAMiddleware (390) sets the full coherent fingerprint first;
    # RotateUserAgentMiddleware (400) is a noop when UA is already set.
    "tools.scrapy_runner.project.middlewares.rotate_ua.RotateUAMiddleware": 390,
    "tools.scrapy_runner.project.middlewares.rotate_ua.RotateUserAgentMiddleware": 400,
    "tools.scrapy_runner.project.middlewares.rotate_proxy.RotateProxyMiddleware": 410,
    "tools.scrapy_runner.project.middlewares.human_delay.HumanDelayMiddleware": 543,
    "tools.scrapy_runner.project.middlewares.risk_signals.RiskMiddleware": 900,
}

RISK_THRESHOLD_WARN = 0.5
RISK_THRESHOLD_BLOCK = 0.8

# --- Session persistence (Step 2.4) ----------------------------------
# Set SESSION_REDIS_URL to activate sticky UA+proxy per session_id.
# Leave None to disable — middlewares fall back to per-request random selection.
SESSION_REDIS_URL = None
SESSION_TTL = 1800  # seconds; Redis key expiry
SESSION_ID = None

# --- Robustness ------------------------------------------------------
RETRY_ENABLED = True
RETRY_TIMES = 2
DOWNLOAD_TIMEOUT = 30
REDIRECT_ENABLED = True
REDIRECT_MAX_TIMES = 5
HTTPERROR_ALLOWED_CODES = []
COOKIES_ENABLED = True

# --- Output ---------------------------------------------------------
LOG_LEVEL = "INFO"
LOG_FORMAT = '{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
TELNETCONSOLE_ENABLED = False
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
