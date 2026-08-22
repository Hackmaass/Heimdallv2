"""
Realistic Synthetic Drone Telemetry Provider
Simulates an autonomous drone loitering over a Pune intersection with dynamic orbit and gimbal adjustments.
"""

import math
from typing import Optional
import numpy as np
from .base import TelemetryProvider, DroneTelemetry


class MockTelemetryProvider(TelemetryProvider):
    """
    Simulates high-fidelity aerial flight telemetry over designated coordinates.
    """

    def __init__(
        self,
        center_lat: float = 18.5308,  # Shivajinagar intersection
        center_lng: float = 73.8475,
        altitude_agl: float = 65.0,
        orbit_radius_deg: float = 0.0008,
    ):
        self.center_lat = center_lat
        self.center_lng = center_lng
        self.altitude_agl = altitude_agl
        self.orbit_radius = orbit_radius_deg

    def get_telemetry(
        self,
        frame: Optional[np.ndarray] = None,
        frame_index: int = 0,
        timestamp: float = 0.0,
    ) -> DroneTelemetry:
        # Slow 60-second orbit around intersection
        angle = (timestamp * 2.0 * math.pi / 60.0)
        lat = self.center_lat + math.sin(angle) * self.orbit_radius
        lng = self.center_lng + math.cos(angle) * self.orbit_radius

        # Tangent heading
        heading = (math.degrees(angle + math.pi / 2.0) + 360.0) % 360.0

        # Gentle altitude variations
        alt = self.altitude_agl + math.sin(timestamp * 0.2) * 1.5

        # Battery slowly draining from 100% to ~85%
        battery = max(15.0, 100.0 - (timestamp * 0.04))

        return DroneTelemetry(
            timestamp=round(timestamp, 3),
            latitude=round(lat, 6),
            longitude=round(lng, 6),
            altitude_agl=round(alt, 1),
            altitude_msl=round(alt + 560.0, 1),
            heading_deg=round(heading, 1),
            ground_speed_mps=8.5,
            vertical_speed_mps=round(math.cos(timestamp * 0.2) * 0.3, 2),
            battery_percentage=round(battery, 1),
            gimbal_pitch_deg=-45.0,
            gimbal_yaw_deg=round((heading + 180.0) % 360.0, 1),
            dock_id="DOCK-01",
            flight_mode="AUTO_ORBIT",
            gps_satellites=19,
        )
