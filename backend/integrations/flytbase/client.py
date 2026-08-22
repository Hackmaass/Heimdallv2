"""
FlytBase API Client Implementation
Supports Live FlytBase Cloud REST API & Mock / Simulation mode
"""

import os
from typing import Optional, Dict, Any
import httpx

from .models import VehicleState, FlytBaseMissionPlan, GimbalCommand, FlytBaseWaypoint
from .virtual_drone import VirtualDrone


class FlytBaseClient:
    """
    Standardized FlytBase Client.
    Connects to physical DiaB drone via FlytBase Cloud or routes commands to VirtualDrone.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        vehicle_id: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        self.api_url = api_url or os.getenv("FLYTBASE_API_URL", "https://api.flytbase.com/v1")
        self.api_key = api_key or os.getenv("FLYTBASE_API_KEY", "")
        self.token = token or os.getenv("FLYTBASE_TOKEN", "")
        self.vehicle_id = vehicle_id or os.getenv("FLYTBASE_VEHICLE_ID", "VIRTUAL-DRONE-01")
        self.mode = mode or os.getenv("FLYTBASE_MODE", "mock" if not self.api_key else "cloud")

        self.virtual_drone = VirtualDrone(vehicle_id=self.vehicle_id)

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock" or not self.api_key

    def get_vehicle_state(self) -> VehicleState:
        """Queries current telemetry & operational status."""
        if self.is_mock:
            return self.virtual_drone.get_state()

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{self.api_url}/vehicles/{self.vehicle_id}/state", headers=headers)
                if res.status_code == 200:
                    d = res.json()
                    return VehicleState(
                        vehicle_id=self.vehicle_id,
                        mode=d.get("mode", "ONLINE"),
                        battery_pct=d.get("battery", 100.0),
                        armed=d.get("armed", False),
                        is_in_air=d.get("in_air", False),
                        current_lat=d.get("lat", 18.5308),
                        current_lng=d.get("lng", 73.8475),
                        current_alt_agl=d.get("altitude", 0.0),
                        heading_deg=d.get("heading", 0.0),
                        speed_mps=d.get("speed", 0.0),
                        gimbal_pitch_deg=d.get("gimbal_pitch", -45.0),
                        dock_id=d.get("dock_id", "DOCK-01"),
                    )
        except Exception:
            pass

        return self.virtual_drone.get_state()

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns JSON-serializable telemetry dictionary."""
        st = self.get_vehicle_state()
        return {
            "vehicle_id": st.vehicle_id,
            "mode": st.mode,
            "battery_pct": st.battery_pct,
            "armed": st.armed,
            "is_in_air": st.is_in_air,
            "position": {"lat": st.current_lat, "lng": st.current_lng, "alt_agl": st.current_alt_agl},
            "heading": st.heading_deg,
            "speed_mps": st.speed_mps,
            "gimbal_pitch": st.gimbal_pitch_deg,
            "dock_id": st.dock_id,
            "connection_status": st.connection_status,
            "is_mock": self.is_mock,
        }

    def get_video_stream(self) -> Dict[str, str]:
        """Returns RTSP/WebRTC stream URLs for live video downlink."""
        if self.is_mock:
            return {
                "type": "simulated_rtsp",
                "rtsp_url": f"rtsp://localhost:8554/{self.vehicle_id}",
                "webrtc_url": f"wss://localhost:8443/{self.vehicle_id}",
                "status": "ONLINE (MOCK)",
            }

        return {
            "type": "flytbase_cloud_stream",
            "rtsp_url": f"{self.api_url}/vehicles/{self.vehicle_id}/live/rtsp",
            "webrtc_url": f"{self.api_url}/vehicles/{self.vehicle_id}/live/webrtc",
            "status": "ONLINE",
        }

    def set_gimbal(self, pitch: float, roll: float = 0.0, yaw: float = 0.0) -> bool:
        cmd = GimbalCommand(pitch=pitch, roll=roll, yaw=yaw)
        if self.is_mock:
            return self.virtual_drone.set_gimbal(cmd)

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            with httpx.Client(timeout=2.0) as client:
                res = client.post(
                    f"{self.api_url}/vehicles/{self.vehicle_id}/gimbal",
                    headers=headers,
                    json={"pitch": pitch, "roll": roll, "yaw": yaw},
                )
                return res.status_code in [200, 202]
        except Exception:
            return False

    def execute_navigation(self, lat: float, lng: float, alt: float = 60.0, speed: float = 12.0) -> bool:
        if self.is_mock:
            return self.virtual_drone.execute_navigation(lat, lng, alt, speed)

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            with httpx.Client(timeout=2.0) as client:
                res = client.post(
                    f"{self.api_url}/vehicles/{self.vehicle_id}/navigation/goto",
                    headers=headers,
                    json={"lat": lat, "lng": lng, "alt": alt, "speed": speed},
                )
                return res.status_code in [200, 202]
        except Exception:
            return False

    def execute_mission(self, plan: FlytBaseMissionPlan) -> bool:
        if self.is_mock:
            return self.virtual_drone.execute_mission(plan)

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            payload = {
                "mission_id": plan.mission_id,
                "waypoints": [{"lat": w.lat, "lng": w.lng, "alt": w.altitude, "speed": w.speed, "action": w.action} for w in plan.waypoints],
                "gimbal_pitch": plan.gimbal_pitch,
            }
            with httpx.Client(timeout=2.0) as client:
                res = client.post(
                    f"{self.api_url}/missions/execute",
                    headers=headers,
                    json=payload,
                )
                return res.status_code in [200, 202]
        except Exception:
            return False

    def return_to_home(self) -> bool:
        if self.is_mock:
            return self.virtual_drone.return_to_home()

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            with httpx.Client(timeout=2.0) as client:
                res = client.post(f"{self.api_url}/vehicles/{self.vehicle_id}/rth", headers=headers)
                return res.status_code in [200, 202]
        except Exception:
            return False
