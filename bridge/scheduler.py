"""APScheduler integration for Chimera bridge."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False
    AsyncIOScheduler = None  # type: ignore[assignment,misc]

scheduler = AsyncIOScheduler() if _APSCHEDULER_AVAILABLE else None


async def _run_daily_factory_job(new_profiles_count: int, db_path: Path, profiles_dir: Path) -> None:
    from tools.account_factory.factory import AccountFactory
    factory = AccountFactory(db_path=db_path, profiles_dir=profiles_dir)
    try:
        report = await factory.daily_factory_run(new_profiles_count=new_profiles_count)
        logger.info("daily_factory_run completed", extra={"report": report})
    except Exception as exc:
        logger.error("daily_factory_run failed: %s", exc)


def setup_scheduler(app, settings) -> None:
    """Wire APScheduler to the FastAPI app lifecycle."""
    if not getattr(settings, "factory_cron_enabled", False):
        return
    if not _APSCHEDULER_AVAILABLE or scheduler is None:
        logger.warning("apscheduler not installed — cron disabled")
        return

    new_profiles = getattr(settings, "factory_new_profiles_per_day", 2)
    db_path = settings.risk_db_path
    profiles_dir = settings.cookies_dir

    scheduler.add_job(
        _run_daily_factory_job,
        trigger="cron",
        hour=9, minute=0,
        id="daily_factory",
        replace_existing=True,
        kwargs={
            "new_profiles_count": new_profiles,
            "db_path": db_path,
            "profiles_dir": profiles_dir,
        },
    )
    scheduler.start()
    logger.info("APScheduler started — daily_factory at 09:00")

    @app.on_event("shutdown")
    def shutdown_scheduler() -> None:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler stopped")
