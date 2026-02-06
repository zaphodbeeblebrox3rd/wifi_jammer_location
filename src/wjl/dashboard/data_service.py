"""Data service for querying WiFi jamming monitoring data."""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from ..config import Config
from ..database import Database

logger = logging.getLogger(__name__)

# RF / jamming metrics only (slim schema)
RF_METRICS = [
    "wifi_channel",
    "wifi_util_pct",
    "noise_dbm",
    "deauth_count",
    "disassoc_count",
    "local_wifi_signal_dbm",
    "local_wifi_noise_dbm",
    "rf_jam_detected",
]

METRIC_DISPLAY = {
    "wifi_channel": ("WiFi Channel", ""),
    "wifi_util_pct": ("WiFi Utilization", "%"),
    "noise_dbm": ("Noise", "dBm"),
    "deauth_count": ("Deauth Count", ""),
    "disassoc_count": ("Disassoc Count", ""),
    "local_wifi_signal_dbm": ("Signal", "dBm"),
    "local_wifi_noise_dbm": ("Noise Floor", "dBm"),
    "rf_jam_detected": ("RF Jam Detected", ""),
}


class DataService:
    """Service for querying WiFi jamming monitoring data."""

    def __init__(self, database: Database, config: Config):
        self.database = database
        self.config = config

    def get_time_series_data(
        self,
        start_time: datetime,
        end_time: datetime,
        metrics: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Get time series data for specified time range and metrics (RF/jamming only).
        """
        if self.database.conn is None:
            raise RuntimeError("Database connection not initialized")

        if metrics:
            valid = [m for m in metrics if m in RF_METRICS or m == "node_id"]
            if not valid:
                return pd.DataFrame(columns=["timestamp"])
            columns = ", ".join(["timestamp"] + valid)
        else:
            columns = "timestamp, node_id, " + ", ".join(RF_METRICS)

        query = f"""
            SELECT {columns}
            FROM monitoring_data
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        try:
            df = pd.read_sql_query(
                query,
                self.database.conn,
                params=(start_time.isoformat(), end_time.isoformat()),
                parse_dates=["timestamp"],
            )
            return df
        except Exception as e:
            logger.error(f"Error querying time series data: {e}")
            return pd.DataFrame()

    def get_available_metrics(self) -> List[Dict[str, str]]:
        """Get list of RF/jamming metrics with display name and unit."""
        metrics = []
        for name in RF_METRICS:
            display_name, unit = METRIC_DISPLAY.get(name, (name.replace("_", " ").title(), ""))
            metrics.append({
                "name": name,
                "display_name": display_name,
                "category": "local_wifi",
                "unit": unit,
            })
        return metrics

    def get_data_range(self) -> Dict:
        """Get the actual time range of data in the database."""
        if self.database.conn is None:
            raise RuntimeError("Database connection not initialized")
        cursor = self.database.conn.cursor()
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM monitoring_data")
        result = cursor.fetchone()
        if result and result[0] and result[1]:
            return {"min_timestamp": result[0], "max_timestamp": result[1]}
        return {}

    def get_summary_stats(
        self, start_time: datetime, end_time: datetime
    ) -> Dict:
        """Get summary statistics for the time range (RF metrics only)."""
        df = self.get_time_series_data(start_time, end_time)
        if df.empty:
            return {}
        stats = {
            "data_points": len(df),
            "time_range": {"start": start_time.isoformat(), "end": end_time.isoformat()},
        }
        for metric in RF_METRICS:
            if metric in df.columns:
                values = df[metric].dropna()
                if len(values) > 0:
                    try:
                        stats[metric] = {
                            "mean": float(values.mean()),
                            "min": float(values.min()),
                            "max": float(values.max()),
                            "std": float(values.std()),
                        }
                    except (TypeError, ValueError):
                        pass
        return stats

    def get_nodes_for_map(self) -> List[Dict]:
        """Get nodes with id, name, latitude, longitude for dashboard map.
        Includes DB nodes plus the relay's own node from config (node.name / node.location) when set.
        """
        nodes = self.database.get_nodes_for_map()
        lat = self.config.node_latitude()
        lon = self.config.node_longitude()
        if lat is not None and lon is not None:
            name = self.config.node_name() or "Relay"
            nodes = [{"id": "relay", "name": name, "latitude": lat, "longitude": lon, "last_seen": None}] + nodes
        return nodes
