"""
Traffic Analytics Engine Foundation
Implements Level 1 metrics (counts, active tracks, density, average speeds)
and defines clean interfaces for higher-level Level 2+ analytics.
"""

from typing import List, Dict, Any, Optional
from .metrics import ClassDistribution, DensityMetric, SpeedMetric
from ..trajectories.models import TrackTrajectory
from ..perception.classification.taxonomy import RoadUserClass


class TrafficAnalyticsEngine:
    """
    Core Traffic Analytics Engine.
    Processes live trajectory state into structured metrics.
    """

    def __init__(self, frame_width: int = 1920, frame_height: int = 1080):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.frame_area_mp = (frame_width * frame_height) / 1_000_000.0

    def calculate_class_distribution(
        self,
        active_tracks: List[TrackTrajectory],
        all_tracks: List[TrackTrajectory],
    ) -> ClassDistribution:
        """Computes current active and cumulative object breakdown by taxonomy class."""
        counts = {c.value: 0 for c in RoadUserClass}
        for t in active_tracks:
            cls_key = t.normalized_class.value
            counts[cls_key] = counts.get(cls_key, 0) + 1

        total_active = len(active_tracks)
        percentages = {
            k: round((v / total_active * 100.0), 1) if total_active > 0 else 0.0
            for k, v in counts.items()
        }

        return ClassDistribution(
            counts=counts,
            percentages=percentages,
            total_active=total_active,
            total_cumulative=len(all_tracks),
        )

    def calculate_density(self, active_tracks: List[TrackTrajectory]) -> DensityMetric:
        """
        Level 1: Computes spatial density (active objects per megapixel).
        """
        count = len(active_tracks)
        density_mp = count / max(0.1, self.frame_area_mp)

        if count < 5:
            level = "LOW"
        elif count < 15:
            level = "MODERATE"
        elif count < 30:
            level = "HEAVY"
        else:
            level = "GRIDLOCK"

        return DensityMetric(
            objects_per_megapixel=round(density_mp, 2),
            raw_active_count=count,
            congestion_level=level,
            is_calibrated=False,
        )

    def calculate_average_speed(self, active_tracks: List[TrackTrajectory]) -> SpeedMetric:
        """
        Level 1: Computes average speed and percentiles across active road users.
        """
        speeds = [t.current_speed for t in active_tracks if t.current_speed > 0]
        if not speeds:
            return SpeedMetric(
                average_speed=0.0,
                unit="px/s",
                speed_percentiles={"p50": 0.0, "p85": 0.0, "p95": 0.0},
                fastest_track_id=None,
                fastest_speed=0.0,
                is_calibrated=False,
            )

        sorted_speeds = sorted(speeds)
        n = len(sorted_speeds)
        avg = sum(sorted_speeds) / n
        p50 = sorted_speeds[int(n * 0.50)]
        p85 = sorted_speeds[min(n - 1, int(n * 0.85))]
        p95 = sorted_speeds[min(n - 1, int(n * 0.95))]

        fastest_track = max(active_tracks, key=lambda t: t.current_speed)

        return SpeedMetric(
            average_speed=round(avg, 2),
            unit="px/s",
            speed_percentiles={"p50": round(p50, 2), "p85": round(p85, 2), "p95": round(p95, 2)},
            fastest_track_id=fastest_track.track_id,
            fastest_speed=round(fastest_track.current_speed, 2),
            is_calibrated=False,
        )

    # ── Level 2+ Extensible Interfaces (Honest Stubs) ──────────────────────────

    def calculate_flow(self) -> Dict[str, Any]:
        """Vehicle flow rate crossing virtual tripwires (Level 2+)."""
        return {"status": "NOT_IMPLEMENTED", "stage": "LEVEL_2", "flow_rate": None}

    def calculate_queue_length(self) -> Dict[str, Any]:
        """Intersection queue length measurement (Level 2+)."""
        return {"status": "NOT_IMPLEMENTED", "stage": "LEVEL_2", "queue_length_meters": None}

    def detect_stopped_vehicle(self, active_tracks: List[TrackTrajectory], min_duration_sec: float = 10.0) -> List[Dict[str, Any]]:
        """Detects vehicles that have remained stationary exceeding threshold."""
        stopped = []
        for t in active_tracks:
            if t.normalized_class in [RoadUserClass.CAR, RoadUserClass.LGV, RoadUserClass.HGV, RoadUserClass.BUS]:
                if t.duration_seconds >= min_duration_sec and t.average_speed < 3.0:
                    stopped.append({
                        "track_id": t.track_id,
                        "class": t.normalized_class.value,
                        "duration_stationary": round(t.duration_seconds, 1),
                        "centroid": t.current_centroid,
                    })
        return stopped

    def detect_near_collision(self) -> Dict[str, Any]:
        """Time-To-Collision (TTC) & spatial proximity analysis (Level 2+)."""
        return {"status": "NOT_IMPLEMENTED", "stage": "LEVEL_2", "events": []}

    def detect_wrong_way(self) -> Dict[str, Any]:
        """Vector orientation check against designated lane flow (Level 2+)."""
        return {"status": "NOT_IMPLEMENTED", "stage": "LEVEL_2", "violations": []}

    def detect_interaction(self) -> Dict[str, Any]:
        """Pedestrian-Vehicle conflict zone interactions (Level 2+)."""
        return {"status": "NOT_IMPLEMENTED", "stage": "LEVEL_2", "interactions": []}

    def detect_congestion(self, active_tracks: List[TrackTrajectory]) -> Dict[str, Any]:
        """Basic congestion detection based on density and average speed."""
        density = self.calculate_density(active_tracks)
        speed = self.calculate_average_speed(active_tracks)
        is_congested = (density.raw_active_count >= 15 and speed.average_speed < 8.0)
        return {
            "is_congested": is_congested,
            "congestion_level": density.congestion_level,
            "active_vehicles": density.raw_active_count,
            "average_speed": speed.average_speed,
        }
