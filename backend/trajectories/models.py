"""
Trajectory Data Models & Schema
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
from ..perception.classification.taxonomy import RoadUserClass


@dataclass
class TrajectoryPoint:
    """A single spatial-temporal coordinate observation along a track's lifetime."""
    frame_index: int
    timestamp: float
    bbox: List[float]  # [x1, y1, x2, y2]
    centroid: Tuple[float, float]  # (cx, cy)
    velocity: Tuple[float, float]  # (vx, vy)
    speed_estimate: float          # relative px/s or ground km/h
    heading: float                 # [0, 360)
    confidence: float
    ground_point: Optional[Tuple[float, float]] = None  # (gx, gy) in meters if calibrated


@dataclass
class TrackTrajectory:
    """Full persistent trajectory history for a tracked entity."""
    track_id: int
    raw_class: str
    normalized_class: RoadUserClass
    confidence: float
    first_seen: float
    last_seen: float
    first_frame: int
    last_frame: int
    total_frames: int
    is_active: bool
    is_uncertain: bool
    current_bbox: List[float]
    current_centroid: Tuple[float, float]
    current_speed: float
    current_heading: float
    history: List[TrajectoryPoint] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.last_seen - self.first_seen)

    @property
    def total_distance_pixels(self) -> float:
        if len(self.history) < 2:
            return 0.0
        dist = 0.0
        for i in range(1, len(self.history)):
            p0 = self.history[i - 1].centroid
            p1 = self.history[i].centroid
            dx = p1[0] - p0[0]
            dy = p1[1] - p0[1]
            dist += (dx * dx + dy * dy) ** 0.5
        return dist

    @property
    def average_speed(self) -> float:
        if not self.history:
            return 0.0
        speeds = [p.speed_estimate for p in self.history if p.speed_estimate > 0]
        return float(sum(speeds) / len(speeds)) if speeds else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "raw_class": self.raw_class,
            "normalized_class": self.normalized_class.value,
            "confidence": round(self.confidence, 3),
            "first_seen": round(self.first_seen, 3),
            "last_seen": round(self.last_seen, 3),
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "total_frames": self.total_frames,
            "duration_seconds": round(self.duration_seconds, 2),
            "is_active": self.is_active,
            "is_uncertain": self.is_uncertain,
            "current_bbox": [round(v, 1) for v in self.current_bbox],
            "current_centroid": [round(v, 1) for v in self.current_centroid],
            "current_speed": round(self.current_speed, 2),
            "current_heading": round(self.current_heading, 1),
            "total_distance_pixels": round(self.total_distance_pixels, 1),
            "average_speed": round(self.average_speed, 2),
            "trail_points_count": len(self.history),
        }
