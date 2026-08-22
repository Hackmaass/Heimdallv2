"""
Trajectory Data Models & Schema (Level 1 + Level 2 Extended Kinematics)
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
from ..perception.classification.taxonomy import RoadUserClass
from ..perception.classification.fine_grained import FineGrainedClass
from .quality import KinematicQualityFlag


@dataclass
class TrajectoryPoint:
    """A single spatial-temporal coordinate observation along a track's lifetime."""
    frame_index: int
    timestamp: float
    bbox: List[float]  # [x1, y1, x2, y2]
    centroid: Tuple[float, float]  # (cx, cy)
    velocity: Tuple[float, float]  # (vx, vy) in px/s
    speed_estimate: float          # relative px/s or ground km/h
    heading: float                 # [0, 360)
    confidence: float

    # ── Level 2 Extended Kinematics ──────────────────────────────────────────
    ground_point: Optional[Tuple[float, float]] = None  # (X, Y) in ground meters
    velocity_mps: Optional[float] = None                # Velocity in m/s
    velocity_kmh: Optional[float] = None                # Velocity in km/h
    acceleration_mps2: Optional[float] = None           # Acceleration in m/s²
    distance_increment_m: float = 0.0                   # Incremental distance in meters
    quality_flag: str = KinematicQualityFlag.VALID_HIGH_CONFIDENCE.value
    fine_grained_class: str = "Car"
    fine_grained_confidence: float = 0.90


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

    # ── Level 2 Extended Kinematics & Fine-Grained Attributes ─────────────────
    fine_grained_class: str = "Car"
    fine_grained_confidence: float = 0.90
    current_world_pos: Optional[Tuple[float, float]] = None # (X, Y) in meters
    current_velocity_mps: Optional[float] = None            # m/s
    current_velocity_kmh: Optional[float] = None            # km/h
    current_acceleration_mps2: Optional[float] = None       # m/s²
    total_distance_meters: float = 0.0                      # Cumulative meters
    is_calibrated: bool = False
    speed_unit: str = "px/s"
    quality_flag: str = KinematicQualityFlag.VALID_HIGH_CONFIDENCE.value

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

    @property
    def average_velocity_kmh(self) -> Optional[float]:
        if not self.history or not self.is_calibrated:
            return None
        kmh_vals = [p.velocity_kmh for p in self.history if p.velocity_kmh is not None and p.velocity_kmh > 0]
        return float(sum(kmh_vals) / len(kmh_vals)) if kmh_vals else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "raw_class": self.raw_class,
            "normalized_class": self.normalized_class.value,
            "fine_grained_class": self.fine_grained_class,
            "fine_grained_confidence": round(self.fine_grained_confidence, 3),
            "confidence": round(self.confidence, 3),
            "first_seen": round(self.first_seen, 3),
            "last_seen": round(self.last_seen, 3),
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "total_frames": self.total_frames,
            "duration_seconds": round(self.duration_seconds, 2),
            "is_active": self.is_active,
            "is_uncertain": self.is_uncertain,
            "is_calibrated": self.is_calibrated,
            "speed_unit": self.speed_unit,
            "quality_flag": self.quality_flag,
            "current_bbox": [round(v, 1) for v in self.current_bbox],
            "current_centroid": [round(v, 1) for v in self.current_centroid],
            "current_world_pos": [round(v, 2) for v in self.current_world_pos] if self.current_world_pos else None,
            "current_speed": round(self.current_speed, 2),
            "current_velocity_mps": round(self.current_velocity_mps, 2) if self.current_velocity_mps is not None else None,
            "current_velocity_kmh": round(self.current_velocity_kmh, 1) if self.current_velocity_kmh is not None else None,
            "current_acceleration_mps2": round(self.current_acceleration_mps2, 2) if self.current_acceleration_mps2 is not None else None,
            "current_heading": round(self.current_heading, 1),
            "total_distance_pixels": round(self.total_distance_pixels, 1),
            "total_distance_meters": round(self.total_distance_meters, 2),
            "average_speed": round(self.average_speed, 2),
            "average_velocity_kmh": round(self.average_velocity_kmh, 1) if self.average_velocity_kmh is not None else None,
            "trail_points_count": len(self.history),
        }
