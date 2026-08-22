"""
Base Multi-Object Tracker Interface & Data Structures
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np
from ..classification.taxonomy import NormalizedClassification


@dataclass
class TrackedObject:
    """An actively tracked road user."""
    track_id: int
    raw_class: str
    normalized: NormalizedClassification
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2]
    centroid: Tuple[float, float]
    velocity: Tuple[float, float] = (0.0, 0.0)  # (vx, vy) in px/s
    speed_estimate: float = 0.0                 # relative px/s or real km/h
    heading: float = 0.0                        # direction in degrees [0, 360)
    is_stationary: bool = False
    first_seen_timestamp: float = 0.0
    last_seen_timestamp: float = 0.0
    frame_count: int = 1


@dataclass
class TrackingResult:
    """Result of tracker update for a single frame."""
    frame_index: int
    timestamp: float
    tracks: List[TrackedObject]
    active_count: int
    lost_count: int = 0


class BaseTracker(ABC):
    """Abstract interface for Multi-Object Trackers."""

    @abstractmethod
    def update(
        self,
        frame: np.ndarray,
        frame_index: int,
        timestamp: float,
    ) -> TrackingResult:
        """Updates tracker state with new video frame."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Resets tracker state."""
        pass
