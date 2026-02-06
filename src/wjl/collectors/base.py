"""Base classes for data collectors."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Base class for all data collectors."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize collector.

        Args:
            config: Configuration dictionary for this collector
        """
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)

    @abstractmethod
    def collect(self) -> Dict[str, Any]:
        """
        Collect data and return as dictionary.

        Returns:
            Dictionary of collected metrics. Keys should match database column names.
        """
        pass

    def is_enabled(self) -> bool:
        """Check if collector is enabled."""
        return self.enabled

    def _handle_error(self, error: Exception, context: str = "") -> Dict[str, Any]:
        """
        Handle errors during collection.

        Args:
            error: Exception that occurred
            context: Additional context about where error occurred

        Returns:
            Empty dictionary or error information
        """
        logger.error(f"Error in {self.__class__.__name__} {context}: {error}")
        return {}
