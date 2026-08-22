"""
Traffic Analytics Engine (Level 1 Baseline + Level 2 Object-Level Insights)
Implements counts, density, average speeds, fine-grained category distributions,
and category-wise speed spectra from actual tracked data.
"""

from typing import List, Dict, Any, Optional
from .metrics import ClassDistribution, FineGrainedDistribution, DensityMetric, SpeedMetric, CategorySpeedBreakdown
from ..trajectories.models import TrackTrajectory
from ..perception.classification.taxonomy import RoadUserClass
from ..perception.classification.fine_grained import FineGrainedClass


class TrafficAnalyticsEngine:
    """
    Core Traffic Analytics Engine.
    Processes live trajectory state into structured object-level and spatial metrics.
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

    def calculate_fine_grained_distribution(
        self,
        active_tracks: List[TrackTrajectory],
    ) -> FineGrainedDistribution:
        """Level 2: Computes breakdown across all 13 fine-grained vehicle and VRU classes."""
        counts = {c.value: 0 for c in FineGrainedClass}
        for t in active_tracks:
            cls_name = getattr(t, "fine_grained_class", t.normalized_class.value)
            counts[cls_name] = counts.get(cls_name, 0) + 1

        total_active = len(active_tracks)
        percentages = {
            k: round((v / total_active * 100.0), 1) if total_active > 0 else 0.0
            for k, v in counts.items()
        }

        return FineGrainedDistribution(
            counts=counts,
            percentages=percentages,
            total_active=total_active,
        )

    def calculate_category_speed_breakdown(
        self,
        active_tracks: List[TrackTrajectory],
    ) -> List[CategorySpeedBreakdown]:
        """Level 2: Computes speed metrics grouped by fine-grained vehicle category."""
        grouped: Dict[str, List[float]] = {}
        unit = "px/s"

        for t in active_tracks:
            if t.current_speed > 0:
                cls_name = getattr(t, "fine_grained_class", t.normalized_class.value)
                if cls_name not in grouped:
                    grouped[cls_name] = []
                grouped[cls_name].append(t.current_speed)
                if getattr(t, "is_calibrated", False):
                    unit = "km/h"

        results = []
        for cat, speeds in grouped.items():
            avg_s = sum(speeds) / len(speeds)
            max_s = max(speeds)
            results.append(CategorySpeedBreakdown(
                category=cat,
                count=len(speeds),
                avg_speed=round(avg_s, 1),
                max_speed=round(max_s, 1),
                unit=unit,
            ))

        return sorted(results, key=lambda r: r.count, reverse=True)

    def calculate_density(self, active_tracks: List[TrackTrajectory]) -> DensityMetric:
        """Computes spatial density (active objects per megapixel)."""
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
        """Computes average speed and percentiles across active road users."""
        speeds = [t.current_speed for t in active_tracks if t.current_speed > 0]
        is_cal = any(getattr(t, "is_calibrated", False) for t in active_tracks)
        unit = "km/h" if is_cal else "px/s"

        if not speeds:
            return SpeedMetric(
                average_speed=0.0,
                unit=unit,
                speed_percentiles={"p50": 0.0, "p85": 0.0, "p95": 0.0},
                fastest_track_id=None,
                fastest_speed=0.0,
                is_calibrated=is_cal,
            )

        sorted_speeds = sorted(speeds)
        n = len(sorted_speeds)
        avg = sum(sorted_speeds) / n
        p50 = sorted_speeds[int(n * 0.50)]
        p85 = sorted_speeds[min(n - 1, int(n * 0.85))]
        p95 = sorted_speeds[min(n - 1, int(n * 0.95))]

        fastest_track = max(active_tracks, key=lambda t: t.current_speed)

        return SpeedMetric(
            average_speed=round(avg, 1),
            unit=unit,
            speed_percentiles={"p50": round(p50, 1), "p85": round(p85, 1), "p95": round(p95, 1)},
            fastest_track_id=fastest_track.track_id,
            fastest_speed=round(fastest_track.current_speed, 1),
            is_calibrated=is_cal,
        )

    def detect_stopped_vehicle(self, active_tracks: List[TrackTrajectory], min_duration_sec: float = 10.0) -> List[Dict[str, Any]]:
        """Detects vehicles that have remained stationary exceeding threshold."""
        stopped = []
        for t in active_tracks:
            if t.normalized_class in [RoadUserClass.CAR, RoadUserClass.LGV, RoadUserClass.HGV, RoadUserClass.BUS]:
                if t.duration_seconds >= min_duration_sec and t.average_speed < 3.0:
                    stopped.append({
                        "track_id": t.track_id,
                        "class": t.normalized_class.value,
                        "fine_grained_class": getattr(t, "fine_grained_class", t.normalized_class.value),
                        "duration_stationary": round(t.duration_seconds, 1),
                        "centroid": t.current_centroid,
                    })
        return stopped
