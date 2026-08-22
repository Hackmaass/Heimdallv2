"""
Telemetry Data Model & Provider Interfaces
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np


@dataclass
class DroneTelemetry:
    """Standardized drone flight telemetry."""
    timestamp: float
    latitude: float
    longitude: float
    altitude_agl: float      # Above Ground Level in meters
    altitude_msl: float      # Mean Sea Level in meters
    heading_deg: float       # Yaw compass heading [0, 360)
    ground_speed_mps: float  # Ground speed in m/s
    vertical_speed_mps: float
    battery_percentage: float
    gimbal_pitch_deg: float  # e.g. -45.0 degrees
    gimbal_yaw_deg: float
    dock_id: Optional[str] = None
    flight_mode: str = "AUTO_NAV"
    gps_satellites: int = 18


class TelemetryProvider(ABC):
    """Abstract interface for drone telemetry providers."""

    @abstractmethod
    def get_telemetry(
        self,
        frame: Optional[np.ndarray] = None,
        frame_index: int = 0,
        timestamp: float = 0.0,
    ) -> DroneTelemetry:
        """Retrieves or parses telemetry for current frame."""
        pass
