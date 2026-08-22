"""
Physical World Reasoner Interface
Translates deterministic CV measurements into semantic scene descriptions for VLMs / LLMs.
"""

from typing import List, Dict, Any, Optional
from ..trajectories.models import TrackTrajectory
from ..analytics.engine import TrafficAnalyticsEngine
from ..telemetry.base import DroneTelemetry


class PhysicalWorldReasoner:
    """
    Constructs a structured, symbolic scene graph representation of the traffic scene
    for consumption by reasoning models (e.g., Cosmos Reason, Gemini, Sarvam).
    """

    def __init__(self, analytics_engine: Optional[TrafficAnalyticsEngine] = None):
        self.analytics = analytics_engine or TrafficAnalyticsEngine()

    def build_scene_state(
        self,
        active_tracks: List[TrackTrajectory],
        telemetry: Optional[DroneTelemetry] = None,
    ) -> Dict[str, Any]:
        """
        Creates a structured promptable scene state dictionary.
        """
        dist = self.analytics.calculate_class_distribution(active_tracks, active_tracks)
        density = self.analytics.calculate_density(active_tracks)
        speed = self.analytics.calculate_average_speed(active_tracks)
        stopped = self.analytics.detect_stopped_vehicle(active_tracks, min_duration_sec=8.0)

        vehicles_summary = []
        for t in active_tracks:
            vehicles_summary.append({
                "id": t.track_id,
                "class": t.normalized_class.value,
                "speed": t.current_speed,
                "heading": t.current_heading,
                "position": [round(t.current_centroid[0], 1), round(t.current_centroid[1], 1)],
                "stationary": (t.current_speed < 3.0),
                "duration_seconds": round(t.duration_seconds, 1),
            })

        return {
            "scene_type": "aerial_drone_intersection_surveillance",
            "drone_telemetry": {
                "lat": telemetry.latitude if telemetry else None,
                "lng": telemetry.longitude if telemetry else None,
                "alt_agl_meters": telemetry.altitude_agl if telemetry else None,
                "gimbal_pitch": telemetry.gimbal_pitch_deg if telemetry else None,
            },
            "summary_metrics": {
                "total_active_entities": len(active_tracks),
                "class_counts": dist.counts,
                "congestion_level": density.congestion_level,
                "average_speed": speed.average_speed,
                "stopped_vehicles_count": len(stopped),
            },
            "entities": vehicles_summary,
        }

    def generate_natural_language_context(
        self,
        active_tracks: List[TrackTrajectory],
        telemetry: Optional[DroneTelemetry] = None,
    ) -> str:
        """
        Generates a concise markdown situational description for reasoning agents.
        """
        state = self.build_scene_state(active_tracks, telemetry)
        m = state["summary_metrics"]
        counts_str = ", ".join(f"{v} {k.lower()}s" for k, v in m["class_counts"].items() if v > 0) or "None"

        return (
            f"**Aerial Surveillance Situational Report**:\n"
            f"- Active Road Users: {m['total_active_entities']} ({counts_str})\n"
            f"- Congestion Status: {m['congestion_level']} (Average speed: {m['average_speed']} px/s)\n"
            f"- Stationary Road Users: {m['stopped_vehicles_count']}\n"
        )
