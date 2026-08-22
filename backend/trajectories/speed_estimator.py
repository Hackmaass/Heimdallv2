"""
Speed Estimation Module
Supports Mode 1 (Relative Pixel Velocity) and Mode 2 (Ground Plane Metric Speed in km/h)
"""

from abc import ABC, abstractmethod
import math
from typing import Tuple, Optional, NamedTuple
from .homography import RoadPlaneHomography


class SpeedEstimate(NamedTuple):
    value: float
    unit: str  # "px/s" or "km/h"
    is_calibrated: bool
    label: str  # "Relative speed" or "Estimated ground speed"


class BaseSpeedEstimator(ABC):
    """Abstract speed estimator interface."""

    @abstractmethod
    def estimate(
        self,
        current_pos: Tuple[float, float],
        prev_pos: Tuple[float, float],
        dt: float,
    ) -> SpeedEstimate:
        pass


class PixelSpeedEstimator(BaseSpeedEstimator):
    """
    Mode 1: Relative Pixel Speed (px/s).
    Does not assume camera calibration and explicitly outputs 'Relative speed'.
    """

    def estimate(
        self,
        current_pos: Tuple[float, float],
        prev_pos: Tuple[float, float],
        dt: float,
    ) -> SpeedEstimate:
        dt = max(0.001, dt)
        dx = current_pos[0] - prev_pos[0]
        dy = current_pos[1] - prev_pos[1]
        dist_px = math.hypot(dx, dy)
        speed_px_s = dist_px / dt

        return SpeedEstimate(
            value=round(speed_px_s, 2),
            unit="px/s",
            is_calibrated=False,
            label="Relative speed",
        )


class GroundPlaneSpeedEstimator(BaseSpeedEstimator):
    """
    Mode 2: Real-World Metric Ground Speed (km/h) via Homography.
    """

    def __init__(self, homography: RoadPlaneHomography):
        self.homography = homography
        self.fallback = PixelSpeedEstimator()

    def estimate(
        self,
        current_pos: Tuple[float, float],
        prev_pos: Tuple[float, float],
        dt: float,
    ) -> SpeedEstimate:
        if not self.homography.is_calibrated:
            return self.fallback.estimate(current_pos, prev_pos, dt)

        dt = max(0.001, dt)
        g_curr = self.homography.transform_point(current_pos)
        g_prev = self.homography.transform_point(prev_pos)

        if g_curr is None or g_prev is None:
            return self.fallback.estimate(current_pos, prev_pos, dt)

        dx_m = g_curr[0] - g_prev[0]
        dy_m = g_curr[1] - g_prev[1]
        dist_m = math.hypot(dx_m, dy_m)

        speed_m_s = dist_m / dt
        speed_km_h = speed_m_s * 3.6

        return SpeedEstimate(
            value=round(speed_km_h, 1),
            unit="km/h",
            is_calibrated=True,
            label="Calibrated speed",
        )
