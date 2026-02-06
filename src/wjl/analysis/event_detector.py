"""Event detection for WiFi jamming and deauth activity."""

import logging
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)


class NetworkEvent:
    """Represents a detected jamming-related event."""

    def __init__(
        self,
        event_id: str,
        event_type: str,
        severity: str,
        timestamp,
        description: str,
        metrics: Dict,
    ):
        self.event_id = event_id
        self.event_type = event_type
        self.severity = severity
        self.timestamp = timestamp
        self.description = description
        self.metrics = metrics

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "metrics": self.metrics,
        }


class EventDetector:
    """Detects jamming-related events from monitoring data (deauth burst, RF jamming)."""

    def __init__(self, config: Dict):
        self.config = config
        self.thresholds = config.get("thresholds", {})

    def detect_events(self, df: pd.DataFrame) -> List[NetworkEvent]:
        """
        Detect jamming-related events in the dataframe.

        Args:
            df: DataFrame with monitoring data (must have 'timestamp' column)

        Returns:
            List of detected NetworkEvent objects (deauth_burst, rf_jamming, optionally disassoc_burst)
        """
        events = []
        if df.empty or "timestamp" not in df.columns:
            return events

        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        threshold_events = self._detect_threshold_events(df)
        events.extend(threshold_events)
        events.sort(key=lambda e: e.timestamp)
        events = self._deduplicate_events(events)
        logger.info(f"Detected {len(events)} jamming events")
        return events

    def _detect_threshold_events(self, df: pd.DataFrame) -> List[NetworkEvent]:
        """Detect deauth burst, disassoc burst, and RF jamming from thresholds."""
        events = []

        deauth_threshold = self.thresholds.get("deauth_count_threshold", 5)
        if "deauth_count" in df.columns:
            deauth_burst = df[df["deauth_count"] > deauth_threshold]
            for _, row in deauth_burst.iterrows():
                if pd.notna(row["deauth_count"]):
                    count = int(row["deauth_count"])
                    severity = "critical" if count > 20 else ("severe" if count > 10 else "moderate")
                    event = NetworkEvent(
                        event_id=f"deauth_burst_{row['timestamp'].isoformat()}",
                        event_type="deauth_burst",
                        severity=severity,
                        timestamp=row["timestamp"],
                        description=f"Deauth frame burst: {count} deauth frames in capture window",
                        metrics={"deauth_count": count},
                    )
                    events.append(event)

        disassoc_threshold = self.thresholds.get("disassoc_count_threshold", deauth_threshold)
        if "disassoc_count" in df.columns:
            disassoc_burst = df[df["disassoc_count"] > disassoc_threshold]
            for _, row in disassoc_burst.iterrows():
                if pd.notna(row["disassoc_count"]):
                    count = int(row["disassoc_count"])
                    severity = "critical" if count > 20 else ("severe" if count > 10 else "moderate")
                    event = NetworkEvent(
                        event_id=f"disassoc_burst_{row['timestamp'].isoformat()}",
                        event_type="disassoc_burst",
                        severity=severity,
                        timestamp=row["timestamp"],
                        description=f"Disassoc frame burst: {count} disassoc frames in capture window",
                        metrics={"disassoc_count": count},
                    )
                    events.append(event)

        if "rf_jam_detected" in df.columns:
            rf_jam = df[df["rf_jam_detected"] >= 1]
            for _, row in rf_jam.iterrows():
                if pd.notna(row["rf_jam_detected"]) and row["rf_jam_detected"] >= 1:
                    event = NetworkEvent(
                        event_id=f"rf_jamming_{row['timestamp'].isoformat()}",
                        event_type="rf_jamming",
                        severity="severe",
                        timestamp=row["timestamp"],
                        description="High noise or low SNR; possible RF jamming or interference",
                        metrics={"rf_jam_detected": int(row["rf_jam_detected"])},
                    )
                    events.append(event)

        return events

    def _deduplicate_events(self, events: List[NetworkEvent]) -> List[NetworkEvent]:
        """Remove duplicate events in same time window."""
        if not events:
            return events
        deduplicated = []
        seen = set()
        for event in events:
            time_key = event.timestamp.replace(second=0, microsecond=0)
            time_key = time_key.replace(minute=(time_key.minute // 5) * 5)
            key = (event.event_type, time_key)
            if key not in seen:
                seen.add(key)
                deduplicated.append(event)
            else:
                existing = next(e for e in deduplicated if (e.event_type, time_key) == key)
                severity_order = {"critical": 4, "severe": 3, "moderate": 2, "minor": 1}
                if severity_order.get(event.severity, 0) > severity_order.get(existing.severity, 0):
                    deduplicated.remove(existing)
                    deduplicated.append(event)
        return deduplicated
