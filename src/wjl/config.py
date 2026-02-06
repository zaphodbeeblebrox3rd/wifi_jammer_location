"""Configuration management for WiFi Jammer / Deauth Monitor."""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """Configuration manager with YAML file support and environment variable overrides."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to YAML config file. If None, looks for config.yaml in config/ directory.
        """
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "config.yaml"

        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}

        if self.config_path.exists():
            self.load()
        else:
            self._config = self._get_default_config()

    def load(self) -> None:
        """Load configuration from YAML file."""
        with open(self.config_path, "r") as f:
            self._config = yaml.safe_load(f) or {}
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        if "IWC_DATABASE_PATH" in os.environ:
            self._config.setdefault("database", {})["path"] = os.environ["IWC_DATABASE_PATH"]
        # Distributed: relay URL and API key
        if "WIFI_JAMMER_RELAY_URL" in os.environ:
            self._config.setdefault("relay", {})["url"] = os.environ["WIFI_JAMMER_RELAY_URL"]
        if "WIFI_JAMMER_API_KEY" in os.environ:
            self._config.setdefault("relay", {})["api_key"] = os.environ["WIFI_JAMMER_API_KEY"]
        if "WIFI_JAMMER_NODE_NAME" in os.environ:
            self._config.setdefault("node", {})["name"] = os.environ["WIFI_JAMMER_NODE_NAME"]
        if "WIFI_JAMMER_NODE_LATITUDE" in os.environ:
            self._config.setdefault("node", {}).setdefault("location", {})["latitude"] = float(
                os.environ["WIFI_JAMMER_NODE_LATITUDE"]
            )
        if "WIFI_JAMMER_NODE_LONGITUDE" in os.environ:
            self._config.setdefault("node", {}).setdefault("location", {})["longitude"] = float(
                os.environ["WIFI_JAMMER_NODE_LONGITUDE"]
            )

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration values."""
        return {
            "database": {"path": "data/monitoring.db"},
            "role": "relay",  # "relay" or "node"
            "relay": {
                "url": None,
                "api_key": None,
            },
            "node": {
                "name": None,
                "location": {"latitude": None, "longitude": None},
            },
            "devices": {
                "local_wifi": {
                    "enabled": False,
                    "interface": "wlan0",
                    "ssid": None,
                    "channel": None,
                    "monitor_capture_seconds": 30,
                    "deauth_threshold": 5,
                    "jamming_noise_threshold_dbm": -70,
                    "jamming_snr_threshold_db": 10,
                },
            },
            "dashboard": {
                "host": "127.0.0.1",
                "port": 8051,
                "debug": False,
            },
            "event_detection": {
                "thresholds": {
                    "deauth_count_threshold": 5,
                },
            },
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value using dot notation."""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def save(self, path: Optional[str] = None) -> None:
        """Save configuration to YAML file."""
        save_path = Path(path) if path else self.config_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)

    @property
    def database_path(self) -> str:
        return self.get("database.path", "data/monitoring.db")

    def is_relay(self) -> bool:
        return self.get("role", "relay").lower() == "relay"

    def is_node(self) -> bool:
        return self.get("role", "relay").lower() == "node"

    def relay_url(self) -> Optional[str]:
        return self.get("relay.url")

    def relay_api_key(self) -> Optional[str]:
        return self.get("relay.api_key")

    def node_name(self) -> Optional[str]:
        return self.get("node.name")

    def node_latitude(self) -> Optional[float]:
        return self.get("node.location.latitude")

    def node_longitude(self) -> Optional[float]:
        return self.get("node.location.longitude")
