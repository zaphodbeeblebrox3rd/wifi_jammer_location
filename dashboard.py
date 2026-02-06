#!/usr/bin/env python3
"""Dashboard entry point for WiFi Jammer / Deauth Monitor."""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from wjl.config import Config
from wjl.database import Database
from wjl.dashboard.app import DashboardApp


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
    parser = argparse.ArgumentParser(description="WiFi Jammer / Deauth Monitor Dashboard")
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
        "--host",
        type=str,
        help="Host to bind dashboard server (overrides config)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port for dashboard server (overrides config)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (overrides config)",
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)
    logger.info("Starting WiFi Jammer / Deauth Monitor Dashboard")

    try:
        # Load configuration
        config = Config(args.config)
        logger.info(f"Loaded configuration from {config.config_path}")

        # Initialize database
        db_path = config.database_path
        logger.info(f"Using database: {db_path}")
        database = Database(db_path)

        # Get dashboard config
        dashboard_config = config.get("dashboard", {})
        host = args.host or dashboard_config.get("host", "127.0.0.1")  # Default to localhost
        port = args.port or dashboard_config.get("port", 8051)
        debug = args.debug or dashboard_config.get("debug", False)

        # Create and run dashboard
        app = DashboardApp(config, database)
        logger.info(f"Dashboard will be available at http://{host}:{port}")
        app.run(host=host, port=port, debug=debug)

        return 0

    except KeyboardInterrupt:
        logger.info("Dashboard stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
