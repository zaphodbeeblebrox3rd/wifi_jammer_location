#!/usr/bin/env python3
"""Main entry point for WiFi Jammer / Deauth Monitor."""

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SETUP_MARKER = PROJECT_ROOT / ".wjl-setup-done"
WJL_SERVICE_NAME = "wjl"

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from iwc.config import Config
from iwc.database import Database
from iwc.scheduler import MonitoringScheduler
from iwc.dashboard.app import DashboardApp

# ANSI red for prominent warnings (only if stderr is a TTY)
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="WiFi jamming and deauth detection monitor (relay or node)"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        help="Path to configuration file (default: config/config.yaml)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single collection cycle and exit",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon (default: run in foreground)",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Run without starting the dashboard server (dashboard is enabled by default)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start dashboard but don't open browser automatically",
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)
    logger.info("Starting WiFi Jammer / Deauth Monitor")

    try:
        # Load configuration
        config = Config(args.config)
        logger.info(f"Loaded configuration from {config.config_path}")

        # When run by a normal user (not root), without --once/--no-dashboard: check setup and service status
        is_root = getattr(os, "geteuid", lambda: -1)() == 0
        if not args.once and not args.no_dashboard and not is_root:
            dashboard_config = config.get("dashboard", {})
            dash_host = dashboard_config.get("host", "127.0.0.1")
            dash_port = dashboard_config.get("port", 8050)
            browser_host = "localhost" if dash_host == "127.0.0.1" else dash_host
            dashboard_url = f"http://{browser_host}:{dash_port}"

            if not SETUP_MARKER.exists():
                msg = (
                    "Monitoring is not set up as a service. To run in the background "
                    "and open the dashboard at login, run: sudo ./scripts/setup-monitoring.sh"
                )
                use_red = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
                prefix = f"{BOLD}{RED}" if use_red else ""
                suffix = f"{RESET}" if use_red else ""
                print(
                    f"\n{prefix}{msg}{suffix}\n",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                try:
                    r = subprocess.run(
                        ["systemctl", "is-active", WJL_SERVICE_NAME],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if r.returncode == 0 and (r.stdout or "").strip() == "active":
                        print(
                            "Service is already running. Opening dashboard ...",
                            file=sys.stderr,
                            flush=True,
                        )
                        webbrowser.open(dashboard_url)
                        return 0
                except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                    pass
                print(
                    f"Service is not running. Start with: sudo systemctl start {WJL_SERVICE_NAME}. Dashboard: {dashboard_url}",
                    file=sys.stderr,
                    flush=True,
                )

        # Warn if Wi-Fi monitoring is enabled but not running as root
        local_wifi = config.get("devices.local_wifi", {}) or {}
        if local_wifi.get("enabled", False) and not is_root:
            msg = (
                "Wi-Fi monitoring is ENABLED but this process is NOT running as root. "
                "Deauth/RF metrics will not be collected. Run with: sudo python3 main.py"
            )
            logger.warning(msg)
            use_red = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
            prefix = f"{BOLD}{RED}" if use_red else ""
            suffix = f"{RESET}" if use_red else ""
            print(
                f"\n{prefix}*** WARNING: {msg} ***{suffix}\n",
                file=sys.stderr,
                flush=True,
            )

        # Initialize database
        db_path = config.database_path
        logger.info(f"Using database: {db_path}")
        database = Database(db_path)

        # Initialize scheduler
        scheduler = MonitoringScheduler(config, database)

        # Initialize dashboard (enabled by default, unless --no-dashboard is specified)
        dashboard_app = None
        dashboard_thread = None
        if not args.no_dashboard:
            dashboard_config = config.get("dashboard", {})
            host = dashboard_config.get("host", "127.0.0.1")  # Default to localhost
            port = dashboard_config.get("port", 8050)
            debug = dashboard_config.get("debug", False)

            logger.info("Initializing dashboard...")
            dashboard_app = DashboardApp(config, database)

            # Start dashboard in a separate thread
            def run_dashboard():
                try:
                    logger.info(f"Dashboard thread starting on {host}:{port}")
                    dashboard_app.run(host=host, port=port, debug=debug)
                except Exception as e:
                    logger.error(f"Dashboard server failed to start: {e}", exc_info=True)
                    raise

            dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
            dashboard_thread.start()

            # Wait a moment for dashboard to start and verify it's running
            time.sleep(2)
            
            if not dashboard_thread.is_alive():
                logger.error("Dashboard thread died immediately! Check logs above for errors.")
            else:
                logger.info(f"Dashboard thread is running (thread ID: {dashboard_thread.ident})")

            # Open browser (skip when running as root—Chrome/Chromium refuse to run as root)
            browser_host = "localhost" if host == "127.0.0.1" else host
            url = f"http://{browser_host}:{port}"
            if not args.no_browser:
                if getattr(os, "geteuid", lambda: -1)() == 0:
                    logger.info(
                        "Running as root: not opening browser (Chrome/Chromium would error). "
                        "Open the dashboard manually: %s", url
                    )
                else:
                    logger.info(f"Opening dashboard in browser: {url}")
                    webbrowser.open(url)
            else:
                logger.info("Dashboard URL (--no-browser): %s", url)

        if args.once:
            # Run once and exit
            logger.info("Running single collection cycle")
            scheduler.run_once()
            if dashboard_app:
                logger.info("Dashboard is running. Press Ctrl+C to stop.")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
            database.close()
            logger.info("Collection complete")
            return 0

        # Run continuously
        def signal_handler(sig, frame):
            """Handle shutdown signals."""
            logger.info("Received shutdown signal, stopping...")
            scheduler.stop()
            database.close()
            sys.exit(0)

        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start scheduler
        scheduler.start()

        if not args.no_dashboard:
            logger.info("Monitoring and dashboard are running. Press Ctrl+C to stop.")
        elif args.daemon:
            logger.info("Running as daemon")
        else:
            logger.info("Running in foreground (press Ctrl+C to stop)")

        try:
            # Keep main thread alive
            while scheduler.running:
                time.sleep(1)
        except KeyboardInterrupt:
            signal_handler(None, None)

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
