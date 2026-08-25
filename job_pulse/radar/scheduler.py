import time
import threading
import logging
from typing import Optional
from job_pulse.storage.db import JobDatabase
from job_pulse.radar.scanner import CompanyRadarScanner
from job_pulse.radar.discovery_scanner import AllIndiaDiscoveryScanner

logger = logging.getLogger("job_pulse.radar.scheduler")


class RadarBackgroundScheduler:
    """
    Background thread scheduler orchestrating dual radar systems:
    1. Radar 1: Target Company Watchlist Scanner (Dispatches to Target Recipient)
    2. Radar 2: All-India Multi-Portal Opportunity Radar (Dispatches to All-India Recipient & Live Google Sheets)
    """

    def __init__(self, db: Optional[JobDatabase] = None):
        self.db = db or JobDatabase()
        self.target_scanner = CompanyRadarScanner(self.db)
        self.discovery_scanner = AllIndiaDiscoveryScanner(self.db)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_target_scan: float = 0.0
        self._last_discovery_scan: float = 0.0

    def start(self) -> None:
        """Start the background scheduler thread if not already running."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="JobPulseDualRadarWorker")
        self._thread.start()
        logger.info("Dual Radar background scheduler daemon started.")

    def stop(self) -> None:
        """Stop the background scheduler thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("Dual Radar background scheduler stopped.")

    def _run_loop(self) -> None:
        """Periodic background execution loop handling both radar systems."""
        # Initial sleep on startup to let server settle
        time.sleep(10)

        while self._running:
            try:
                config = self.db.get_email_config()
                now = time.time()

                # ----------------------------------------------------
                # Radar 1: Target Company Radar Scan
                # ----------------------------------------------------
                target_enabled = config.get("is_enabled", False)
                target_interval_sec = max(5, int(config.get("check_interval_minutes", 60))) * 60

                if target_enabled and (now - self._last_target_scan >= target_interval_sec):
                    logger.info("Running scheduled Target Company Radar scan across watchlist...")
                    try:
                        self.target_scanner.scan_all_targets(send_email=True)
                        self._last_target_scan = time.time()
                    except Exception as e:
                        logger.error(f"Error during Target Radar scan: {e}", exc_info=True)

                # ----------------------------------------------------
                # Radar 2: All-India Multi-Portal Opportunity Radar
                # ----------------------------------------------------
                all_india_enabled = config.get("all_india_is_enabled", False)
                all_india_interval_sec = max(10, int(config.get("all_india_interval_minutes", 120))) * 60

                if all_india_enabled and (now - self._last_discovery_scan >= all_india_interval_sec):
                    logger.info("Running scheduled All-India Multi-Portal Discovery Radar scan...")
                    try:
                        self.discovery_scanner.scan_all_india(send_email=True, sync_sheets=True)
                        self._last_discovery_scan = time.time()
                    except Exception as e:
                        logger.error(f"Error during All-India Discovery Radar scan: {e}", exc_info=True)

                # Sleep in short increments for responsive shutdown
                for _ in range(6):  # 30 seconds check cycle
                    if not self._running:
                        break
                    time.sleep(5)

            except Exception as e:
                logger.error(f"Error in Dual Radar background loop: {e}", exc_info=True)
                time.sleep(30)


_global_scheduler: Optional[RadarBackgroundScheduler] = None


def get_radar_scheduler(db: Optional[JobDatabase] = None) -> RadarBackgroundScheduler:
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = RadarBackgroundScheduler(db)
    return _global_scheduler

