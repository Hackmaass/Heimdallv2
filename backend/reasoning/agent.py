"""
Traffic Agent Tool-Calling Interface
Exposes structured analytical queries & drone control tools to future LLM/VLM agents.
"""

from typing import List, Dict, Any, Optional
from ..trajectories.engine import TrajectoryEngine
from ..analytics.engine import TrafficAnalyticsEngine
from ..telemetry.base import TelemetryProvider
from ..integrations.flytbase.client import FlytBaseClient


class TrafficAgent:
    """
    Agentic interface providing structured tools for an autonomous reasoning agent.
    """

    def __init__(
        self,
        trajectory_engine: TrajectoryEngine,
        analytics_engine: TrafficAnalyticsEngine,
        telemetry_provider: TelemetryProvider,
        flytbase_client: FlytBaseClient,
    ):
        self.trajectory_engine = trajectory_engine
        self.analytics_engine = analytics_engine
        self.telemetry_provider = telemetry_provider
        self.flytbase_client = flytbase_client

    def get_active_tracks(self) -> List[Dict[str, Any]]:
        """Returns all currently visible road users."""
        active = self.trajectory_engine.get_active_trajectories()
        return [t.to_dict() for t in active]

    def get_track(self, track_id: int) -> Optional[Dict[str, Any]]:
        """Queries single track summary."""
        t = self.trajectory_engine.get_trajectory(track_id)
        return t.to_dict() if t else None

    def get_trajectory(self, track_id: int) -> Optional[List[Dict[str, Any]]]:
        """Returns full historical spatial coordinate trail for an entity."""
        t = self.trajectory_engine.get_trajectory(track_id)
        if not t:
            return None
        return [
            {
                "frame": pt.frame_index,
                "timestamp": pt.timestamp,
                "centroid": pt.centroid,
                "speed": pt.speed_estimate,
                "heading": pt.heading,
            }
            for pt in t.history
        ]

    def get_density(self) -> Dict[str, Any]:
        """Returns current intersection density metrics."""
        active = self.trajectory_engine.get_active_trajectories()
        d = self.analytics_engine.calculate_density(active)
        return {
            "objects_per_megapixel": d.objects_per_megapixel,
            "raw_active_count": d.raw_active_count,
            "congestion_level": d.congestion_level,
        }

    def get_average_speed(self) -> Dict[str, Any]:
        """Returns fleet/intersection speed statistics."""
        active = self.trajectory_engine.get_active_trajectories()
        s = self.analytics_engine.calculate_average_speed(active)
        return {
            "average_speed": s.average_speed,
            "unit": s.unit,
            "percentiles": s.speed_percentiles,
            "fastest_track_id": s.fastest_track_id,
            "fastest_speed": s.fastest_speed,
        }

    def get_congestion(self) -> Dict[str, Any]:
        """Returns overall congestion status."""
        active = self.trajectory_engine.get_active_trajectories()
        return self.analytics_engine.detect_congestion(active)

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns current drone aerial flight telemetry."""
        return self.flytbase_client.get_telemetry()

    def request_gimbal_view(self, pitch_deg: float, yaw_deg: float = 0.0) -> Dict[str, Any]:
        """Commands drone camera gimbal to specific angle."""
        success = self.flytbase_client.set_gimbal(pitch=pitch_deg, yaw=yaw_deg)
        return {"success": success, "pitch_deg": pitch_deg, "yaw_deg": yaw_deg}

    def request_drone_navigation(self, lat: float, lng: float, alt_meters: float = 60.0) -> Dict[str, Any]:
        """Dispatches drone to designated aerial waypoint."""
        success = self.flytbase_client.execute_navigation(lat=lat, lng=lng, alt=alt_meters)
        return {"success": success, "target_lat": lat, "target_lng": lng, "altitude": alt_meters}
