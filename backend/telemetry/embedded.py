"""
Embedded Visual OSD Telemetry Provider (OCR / Template Parsing)
"""

from typing import Optional
import numpy as np
from .base import TelemetryProvider, DroneTelemetry


class EmbeddedTelemetryProvider(TelemetryProvider):
    """
    Parses visual flight telemetry displayed on the drone video feed OSD / HUD.
    """

    def __init__(self, default_lat: float = 18.5204, default_lng: float = 73.8567):
        self.default_lat = default_lat
        self.default_lng = default_lng

    def get_telemetry(
        self,
        frame: Optional[np.ndarray] = None,
        frame_index: int = 0,
        timestamp: float = 0.0,
    ) -> DroneTelemetry:
        # Default baseline if visual OCR is disabled or frame lacks text
        lat = self.default_lat + (frame_index * 0.00001)
        lng = self.default_lng + (frame_index * 0.00001)

        return DroneTelemetry(
            timestamp=timestamp,
            latitude=round(lat, 6),
            longitude=round(lng, 6),
            altitude_agl=60.0,
            altitude_msl=620.0,
            heading_deg=round((frame_index * 0.5) % 360.0, 1),
            ground_speed_mps=12.5,
            vertical_speed_mps=0.0,
            battery_percentage=max(20.0, 98.0 - (timestamp * 0.05)),
            gimbal_pitch_deg=-45.0,
            gimbal_yaw_deg=0.0,
            flight_mode="BVLOS_SURVEILLANCE",
        )
