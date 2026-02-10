"""Continuous WiFi jamming monitoring: back-to-back capture cycles, no interval."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

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


def _push_channel_amplitude_to_relay(
    config: Config, when: datetime, samples: List[Dict[str, Any]]
) -> bool:
    """POST channel amplitude samples to relay. Returns True on success."""
    url = config.relay_url()
    api_key = config.relay_api_key()
    if not url or not api_key or not samples:
        return False
    try:
        import urllib.request
        import json
        endpoint = url.rstrip("/") + "/api/channel_amplitude"
        payload_list = [
            {
                "timestamp": when.isoformat(),
                "channel": s["channel"],
                "signal_dbm": s.get("signal_dbm"),
                "noise_dbm": s.get("noise_dbm"),
            }
            for s in samples
        ]
        payload = json.dumps({"samples": payload_list}).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning("Push channel amplitude to relay failed: %s", e)
        return False


class MonitoringScheduler:
    """Continuous WiFi jamming monitoring: run capture cycles back-to-back (no interval)."""

    def __init__(self, config: Config, database: Database):
        self.config = config
        self.database = database
        self.running = False
        self._monitor_thread = None
        self._channel_scan_thread = None
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

    def _get_channel_scan_config(self) -> Dict:
        """Return channel_scan config dict if enabled; else empty."""
        lw = self.config.get("devices.local_wifi", {}) or {}
        scan = lw.get("channel_scan") or {}
        if not scan.get("enabled", False):
            return {}
        return scan

    def _run_channel_scan_loop(self) -> None:
        """Run per-channel amplitude scan every interval_minutes (only when channel_scan enabled)."""
        scan = self._get_channel_scan_config()
        if not scan:
            return
        interval_sec = max(60, (scan.get("interval_minutes") or 5) * 60)
        channels: List[int] = scan.get("channels") or [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        duration = max(1, min(scan.get("capture_seconds_per_channel") or 10, 30))
        collector = self.collectors.get("local_wifi")
        if not isinstance(collector, LocalWiFiCollector):
            return
        logger.info(
            "Channel scan thread started: every %s min, channels %s, %s s per channel",
            interval_sec // 60, channels, duration,
        )
        first_run = True
        while self.running:
            if not first_run:
                time.sleep(interval_sec)
            first_run = False
            if not self.running:
                break
            if not self._get_channel_scan_config():
                continue
            try:
                when = datetime.now(timezone.utc)
                samples = collector.collect_per_channel(channels, duration)
                node_id = None if self.config.is_relay() else getattr(self.config, "_node_id", None)
                for s in samples:
                    self.database.insert_channel_amplitude(
                        when,
                        node_id,
                        s["channel"],
                        s.get("signal_dbm"),
                        s.get("noise_dbm"),
                    )
                if self.config.is_node() and self.config.relay_url():
                    if _push_channel_amplitude_to_relay(self.config, when, samples):
                        logger.info("Channel amplitude pushed to relay: %s samples", len(samples))
                logger.info("Channel scan completed: %s samples at %s", len(samples), when.isoformat())
            except Exception as e:
                logger.error("Channel scan failed: %s", e, exc_info=True)

    def start(self) -> None:
        """Start continuous monitoring (back-to-back capture cycles)."""
        if self.running:
            logger.warning("Monitor already running")
            return
        self.running = True
        self._monitor_thread = threading.Thread(target=self._run_continuous, daemon=True)
        self._monitor_thread.start()
        logger.info("Continuous monitoring started (back-to-back capture cycles)")
        scan = self._get_channel_scan_config()
        if scan and "local_wifi" in self.collectors:
            self._channel_scan_thread = threading.Thread(
                target=self._run_channel_scan_loop, daemon=True
            )
            self._channel_scan_thread.start()

    def _run_continuous(self) -> None:
        """Run capture cycles. When local_wifi is enabled, enforce minimum interval (monitor_capture_seconds) so we don't flood the DB when tshark fails fast."""
        while self.running:
            if self.collectors:
                start = time.time()
                self._run_collection_cycle()
                elapsed = time.time() - start
                # When local_wifi collector is active, cap cycle rate so we don't store thousands of empty rows if tshark fails immediately (e.g. not root)
                if "local_wifi" in self.collectors:
                    lw = self.config.get("devices.local_wifi", {}) or {}
                    interval = max(1, lw.get("monitor_capture_seconds", 30))
                    sleep_for = interval - elapsed
                    if sleep_for > 0 and self.running:
                        time.sleep(sleep_for)
            else:
                time.sleep(5)

    def stop(self) -> None:
        """Stop continuous monitoring."""
        if not self.running:
            return
        logger.info("Stopping monitor")
        self.running = False
        if self._channel_scan_thread and self._channel_scan_thread.is_alive():
            self._channel_scan_thread.join(timeout=130)
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
