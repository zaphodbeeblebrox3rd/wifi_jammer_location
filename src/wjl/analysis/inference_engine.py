"""Inference engine for jamming-related events (deauth burst, RF jamming)."""

import logging
from typing import Dict, List, Optional

import pandas as pd

from .event_detector import NetworkEvent

logger = logging.getLogger(__name__)


class Inference:
    """Represents an inference about a jamming-related event."""

    def __init__(
        self,
        cause_type: str,
        confidence: str,
        description: str,
        evidence: Dict,
        related_metrics: Optional[Dict] = None,
    ):
        self.cause_type = cause_type
        self.confidence = confidence
        self.description = description
        self.evidence = evidence
        self.related_metrics = related_metrics or {}

    def to_dict(self) -> Dict:
        return {
            "cause_type": self.cause_type,
            "confidence": self.confidence,
            "description": self.description,
            "evidence": self.evidence,
            "related_metrics": self.related_metrics,
        }


class InferenceEngine:
    """Generates inferences for jamming-related events (deauth burst, RF jamming)."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

    def generate_inferences(
        self, event: NetworkEvent, context_data: pd.DataFrame
    ) -> List[Inference]:
        """
        Generate inferences for a jamming-related event.

        Args:
            event: The network event to analyze
            context_data: DataFrame with monitoring data around the event time

        Returns:
            List of Inference objects (wifi_deauth, wifi_rf_jamming only)
        """
        inferences = []
        if context_data.empty:
            return inferences

        if event.event_type == "deauth_burst":
            count = event.metrics.get("deauth_count", 0)
            inferences.append(
                Inference(
                    cause_type="wifi_deauth",
                    confidence="high",
                    description="Deauth frames detected; possible deauth attack or misconfigured device.",
                    evidence={"deauth_count": count},
                    related_metrics={"deauth_count": count},
                )
            )
        elif event.event_type == "rf_jamming":
            inferences.append(
                Inference(
                    cause_type="wifi_rf_jamming",
                    confidence="medium",
                    description="High noise or low SNR; possible RF jamming or interference.",
                    evidence={"rf_jam_detected": event.metrics.get("rf_jam_detected", 1)},
                    related_metrics={},
                )
            )
        elif event.event_type == "disassoc_burst":
            count = event.metrics.get("disassoc_count", 0)
            inferences.append(
                Inference(
                    cause_type="wifi_disassoc",
                    confidence="high",
                    description="Disassoc frames detected; possible attack or client disconnects.",
                    evidence={"disassoc_count": count},
                    related_metrics={"disassoc_count": count},
                )
            )

        confidence_order = {"high": 3, "medium": 2, "low": 1}
        inferences.sort(key=lambda x: confidence_order.get(x.confidence, 0), reverse=True)
        return inferences
