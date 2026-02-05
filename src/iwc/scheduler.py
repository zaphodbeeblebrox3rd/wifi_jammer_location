"""Continuous WiFi jamming monitoring: back-to-back capture cycles, no interval."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict

from .config import Config
from .database import Database
from .collectors.local_wifi import LocalWiFiCollector

logger = logging.getLogger(__name__)

# Slim columns only (for local insert and relay payload)
SLIM_MEASUREMENT_KEYS = frozenset({
    "timestamp", "node_id", "wifi_channel", "wifi_util_pct", "noise_dbm",
    "deauth_count", "disassoc_count", "local_wifi_signal_dbm", "local_wifi_noise_dbm", "rf_jam_detected",
})


def _slim_measurement(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return only slim columns present in data."""
    return {k: v for k, v in data.items() if k in SLIM_MEASUREMENT_KEYS}


def _push_to_relay(config: Config, measurement: Dict[str, Any]) -> bool:
    """POST measurement to relay. Returns True on success."""
    url = config.relay_url()
    api_key = config.relay_api_key()
    if not url or not api_key:
        return False
    try:
        import urllib.request
        import json
        endpoint = url.rstrip("/") + "/api/measurements"
        payload = json.dumps({
            k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in measurement.items()
        }).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning("Push to relay failed: %s", e)
        return False


class MonitoringScheduler:
    """Continuous WiFi jamming monitoring: run capture cycles back-to-back (no interval)."""

    def __init__(self, config: Config, database: Database):
        self.config = config
        self.database = database
        self.running = False
        self._monitor_thread = None
        self._last_collection_time = None
        self.collectors = self._initialize_collectors()

    def _initialize_collectors(self) -> Dict:
        """Initialize only the local WiFi collector."""
        collectors = {}
        local_wifi_config = self.config.get("devices.local_wifi", {})
        if local_wifi_config.get("enabled", False):
            collectors["local_wifi"] = LocalWiFiCollector(local_wifi_config)
        logger.info(f"Initialized {len(collectors)} collectors: {list(collectors.keys())}")
        return collectors

    def _collect_all(self) -> Dict:
        """Collect data from all enabled collectors."""
        result = {"timestamp": datetime.utcnow()}
        for name, collector in self.collectors.items():
            if collector.is_enabled():
                try:
                    data = collector.collect()
                    if data:
                        result.update(data)
                        logger.debug(f"Collected data from {name}: {len(data)} metrics")
                except Exception as e:
                    logger.error(f"Error collecting from {name}: {e}")
        return result

    def _run_collection_cycle(self) -> None:
        """Run a single collection cycle: collect, store locally (relay) and/or push to relay (node)."""
        try:
            current_time = datetime.now(timezone.utc)
            logger.info(f"Starting collection cycle at {current_time.isoformat()}")
            start_time = time.time()

            measurement = self._collect_all()
            if not measurement or len(measurement) <= 1:
                logger.warning("No data collected in this cycle")
                return

            slim = _slim_measurement(measurement)
            if not slim:
                return

            if self.config.is_relay():
                try:
                    self.database.insert_measurement(slim)
                    elapsed = time.time() - start_time
                    self._last_collection_time = current_time
                    logger.info(f"Collection cycle completed in {elapsed:.2f}s, stored {len(slim)} metrics")
                except Exception as db_error:
                    logger.error(f"Database error in collection cycle: {db_error}", exc_info=True)
            elif self.config.is_node():
                if _push_to_relay(self.config, slim):
                    elapsed = time.time() - start_time
                    self._last_collection_time = current_time
                    logger.info(f"Collection cycle completed in {elapsed:.2f}s, pushed to relay")
                else:
                    logger.warning("No relay URL/api_key configured or push failed")
        except Exception as e:
            logger.error(f"Error in collection cycle: {e}", exc_info=True)

    def start(self) -> None:
        """Start continuous monitoring (back-to-back capture cycles)."""
        if self.running:
            logger.warning("Monitor already running")
            return
        self.running = True
        self._monitor_thread = threading.Thread(target=self._run_continuous, daemon=True)
        self._monitor_thread.start()
        logger.info("Continuous monitoring started (back-to-back capture cycles)")

    def _run_continuous(self) -> None:
        """Run capture cycles back-to-back with no delay between them."""
        while self.running:
            if self.collectors:
                self._run_collection_cycle()
            else:
                time.sleep(5)

    def stop(self) -> None:
        """Stop continuous monitoring."""
        if not self.running:
            return
        logger.info("Stopping monitor")
        self.running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=120)
        logger.info("Monitor stopped")

    def run_once(self) -> None:
        """Run a single collection cycle."""
        logger.info("Running single collection cycle")
        self._run_collection_cycle()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
