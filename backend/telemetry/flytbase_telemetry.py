"""
FlytBase Cloud / FlytOS Telemetry Provider
"""

import os
from typing import Optional
import numpy as np
from .base import TelemetryProvider, DroneTelemetry
from .mock import MockTelemetryProvider


class FlytBaseTelemetryProvider(TelemetryProvider):
    """
    Live FlytBase Cloud telemetry provider with automatic fallback to mock simulation.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        vehicle_id: Optional[str] = None,
    ):
        self.api_url = api_url or os.getenv("FLYTBASE_API_URL", "https://api.flytbase.com/v1")
        self.api_key = api_key or os.getenv("FLYTBASE_API_KEY", "")
        self.vehicle_id = vehicle_id or os.getenv("FLYTBASE_VEHICLE_ID", "VIRTUAL-DRONE-01")

        self.mock_fallback = MockTelemetryProvider()
        self.is_live = bool(self.api_key)

    def get_telemetry(
        self,
        frame: Optional[np.ndarray] = None,
        frame_index: int = 0,
        timestamp: float = 0.0,
    ) -> DroneTelemetry:
        if not self.is_live:
            return self.mock_fallback.get_telemetry(frame, frame_index, timestamp)

        # When API credentials are provided, polls FlytBase Cloud REST endpoint
        try:
            import httpx
            headers = {"Authorization": f"Bearer {self.api_key}"}
            url = f"{self.api_url}/vehicles/{self.vehicle_id}/telemetry"
            with httpx.Client(timeout=1.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return DroneTelemetry(
                        timestamp=timestamp,
                        latitude=data.get("lat", 18.5308),
                        longitude=data.get("lng", 73.8475),
                        altitude_agl=data.get("altitude", 60.0),
                        altitude_msl=data.get("altitude_msl", 620.0),
                        heading_deg=data.get("heading", 0.0),
                        ground_speed_mps=data.get("speed", 0.0),
                        vertical_speed_mps=data.get("vz", 0.0),
                        battery_percentage=data.get("battery", 100.0),
                        gimbal_pitch_deg=data.get("gimbal_pitch", -45.0),
                        gimbal_yaw_deg=data.get("gimbal_yaw", 0.0),
                        dock_id=data.get("dock_id", "DOCK-01"),
                        flight_mode=data.get("flight_mode", "GUIDED"),
                    )
        except Exception:
            pass

        return self.mock_fallback.get_telemetry(frame, frame_index, timestamp)
