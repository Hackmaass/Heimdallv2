"""
Traffic Analytics Metric Definitions (Level 1 + Level 2 Extended Kinematic Metrics)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from ..perception.classification.taxonomy import RoadUserClass


@dataclass
class ClassDistribution:
    counts: Dict[str, int]
    percentages: Dict[str, float]
    total_active: int
    total_cumulative: int


@dataclass
class FineGrainedDistribution:
    counts: Dict[str, int]
    percentages: Dict[str, float]
    total_active: int


@dataclass
class DensityMetric:
    objects_per_megapixel: float
    raw_active_count: int
    congestion_level: str  # "LOW", "MODERATE", "HEAVY", "GRIDLOCK"
    is_calibrated: bool = False
    objects_per_100m2: Optional[float] = None


@dataclass
class SpeedMetric:
    average_speed: float
    unit: str  # "px/s" or "km/h"
    speed_percentiles: Dict[str, float]  # p50, p85, p95
    fastest_track_id: Optional[int]
    fastest_speed: float
    is_calibrated: bool


@dataclass
class CategorySpeedBreakdown:
    category: str
    count: int
    avg_speed: float
    max_speed: float
    unit: str
