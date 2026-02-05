"""API endpoints for dashboard data access."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from ..analysis.event_detector import EventDetector, NetworkEvent
from ..analysis.inference_engine import InferenceEngine
from ..config import Config
from .data_service import DataService

logger = logging.getLogger(__name__)


class DashboardAPI:
    """API for dashboard data access."""

    def __init__(self, data_service: DataService, config: Config):
        """
        Initialize dashboard API.

        Args:
            data_service: DataService instance
            config: Configuration instance
        """
        self.data_service = data_service
        self.config = config

        # Initialize event detector and inference engine
        event_config = config.get("event_detection", {})
        self.event_detector = EventDetector(event_config)
        self.inference_engine = InferenceEngine()

    def get_time_series_data(
        self,
        start_time: datetime,
        end_time: datetime,
        metrics: Optional[List[str]] = None,
    ) -> Dict:
        """
        Get time series data for dashboard.

        Args:
            start_time: Start of time range
            end_time: End of time range
            metrics: List of metric names to retrieve

        Returns:
            Dictionary with time series data in format suitable for Plotly
        """
        df = self.data_service.get_time_series_data(start_time, end_time, metrics)

        if df.empty:
            return {"data": [], "timestamps": []}

        # Convert to format suitable for Plotly
        timestamps = df["timestamp"].tolist()
        data = {}

        for col in df.columns:
            if col != "timestamp":
                data[col] = df[col].tolist()

        return {
            "timestamps": [ts.isoformat() for ts in timestamps],
            "data": data,
        }

    def get_events(
        self, start_time: datetime, end_time: datetime
    ) -> List[Dict]:
        """
        Get network events for time range.

        Args:
            start_time: Start of time range
            end_time: End of time range

        Returns:
            List of event dictionaries
        """
        # Get data for event detection
        df = self.data_service.get_time_series_data(start_time, end_time)

        if df.empty:
            return []

        # Detect events
        events = self.event_detector.detect_events(df)

        # Convert to dictionaries
        return [event.to_dict() for event in events]

    def get_event_inferences(self, event: Dict, context_hours: int = 24) -> List[Dict]:
        """
        Get inferences for a specific event.

        Args:
            event: Event dictionary
            context_hours: Hours of context data to analyze around event

        Returns:
            List of inference dictionaries
        """
        event_time = datetime.fromisoformat(event["timestamp"])

        # Get context data around event
        start_time = event_time - timedelta(hours=context_hours)
        end_time = event_time + timedelta(hours=1)

        df = self.data_service.get_time_series_data(start_time, end_time)

        if df.empty:
            return []

        # Convert event dict back to NetworkEvent object
        network_event = NetworkEvent(
            event_id=event["event_id"],
            event_type=event["event_type"],
            severity=event["severity"],
            timestamp=event_time,
            description=event["description"],
            metrics=event.get("metrics", {}),
        )

        # Generate inferences
        inferences = self.inference_engine.generate_inferences(network_event, df)

        return [inf.to_dict() for inf in inferences]

    def get_available_metrics(self) -> List[Dict]:
        """
        Get list of available metrics.

        Returns:
            List of metric dictionaries
        """
        return self.data_service.get_available_metrics()

    def get_summary_stats(
        self, start_time: datetime, end_time: datetime
    ) -> Dict:
        """
        Get summary statistics.

        Args:
            start_time: Start of time range
            end_time: End of time range

        Returns:
            Dictionary with summary statistics
        """
        return self.data_service.get_summary_stats(start_time, end_time)

    def get_data_range(self) -> Dict:
        """
        Get the actual time range of data in the database.

        Returns:
            Dictionary with min_timestamp and max_timestamp, or empty dict if no data
        """
        return self.data_service.get_data_range()

    def get_nodes(self) -> List[Dict]:
        """
        Get nodes for map (id, name, latitude, longitude, last_seen).

        Returns:
            List of node dictionaries for dashboard map
        """
        return self.data_service.get_nodes_for_map()
