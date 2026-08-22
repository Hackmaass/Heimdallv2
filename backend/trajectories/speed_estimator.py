"""
Kinematics & Speed Estimation Engine
Supports:
  - Mode 1: Relative Pixel Velocity (px/s) when uncalibrated
  - Mode 2: Real-World Metric Ground Kinematics via Homography (m/s, km/h, m/s², distance in meters)
"""

from abc import ABC, abstractmethod
import math
from typing import Tuple, Optional, NamedTuple, List
from .homography import RoadPlaneHomography
from .quality import KinematicQualityAssessor, KinematicQualityFlag, QualityAssessment


class SpeedEstimate(NamedTuple):
    value: float
    unit: str  # "px/s" or "km/h"
    is_calibrated: bool
    label: str  # "Relative speed" or "Estimated ground speed"


class KinematicState(NamedTuple):
    speed_value: float              # px/s if uncalibrated, km/h if calibrated
    speed_unit: str                 # "px/s" or "km/h"
    velocity_mps: Optional[float]   # Ground speed in m/s (or None if uncalibrated)
    velocity_kmh: Optional[float]   # Ground speed in km/h (or None if uncalibrated)
    acceleration_mps2: Optional[float] # Acceleration in m/s² (or None if uncalibrated)
    world_pos: Optional[Tuple[float, float]] # (X, Y) in ground meters
    heading_deg: float              # [0, 360)
    distance_increment_m: float     # Distance traversed in this frame (meters)
    is_calibrated: bool             # Calibration status
    quality_assessment: QualityAssessment # Reliability assessment


class BaseSpeedEstimator(ABC):
    """Abstract speed estimator interface."""

    @abstractmethod
    def estimate_kinematics(
        self,
        current_bbox: List[float],
        prev_bbox: Optional[List[float]],
        dt: float,
        prev_velocity_mps: Optional[float] = None,
        history_length: int = 1,
    ) -> KinematicState:
        pass

    def estimate(
        self,
        current_pos: Tuple[float, float],
        prev_pos: Tuple[float, float],
        dt: float,
    ) -> SpeedEstimate:
        """Backward compatibility method for centroid-pair speed estimation."""
        dt = max(0.001, dt)
        dx = current_pos[0] - prev_pos[0]
        dy = current_pos[1] - prev_pos[1]
        dist = math.hypot(dx, dy)
        return SpeedEstimate(
            value=round(dist / dt, 2),
            unit="px/s",
            is_calibrated=False,
            label="Relative speed",
        )


class PixelSpeedEstimator(BaseSpeedEstimator):
    """
    Mode 1: Relative Pixel Speed (px/s) for Uncalibrated Operation.
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

    def estimate_kinematics(
        self,
        current_bbox: List[float],
        prev_bbox: Optional[List[float]],
        dt: float,
        prev_velocity_mps: Optional[float] = None,
        history_length: int = 1,
    ) -> KinematicState:
        dt = max(0.001, dt)
        curr_cx = (current_bbox[0] + current_bbox[2]) / 2.0
        curr_cy = (current_bbox[1] + current_bbox[3]) / 2.0

        if prev_bbox is None:
            return KinematicState(
                speed_value=0.0,
                speed_unit="px/s",
                velocity_mps=None,
                velocity_kmh=None,
                acceleration_mps2=None,
                world_pos=None,
                heading_deg=0.0,
                distance_increment_m=0.0,
                is_calibrated=False,
                quality_assessment=KinematicQualityAssessor.assess(
                    is_calibrated=False,
                    history_length=history_length,
                    dt=dt,
                    speed_mps=None,
                    accel_mps2=None,
                ),
            )

        prev_cx = (prev_bbox[0] + prev_bbox[2]) / 2.0
        prev_cy = (prev_bbox[1] + prev_bbox[3]) / 2.0

        dx = curr_cx - prev_cx
        dy = curr_cy - prev_cy
        dist_px = math.hypot(dx, dy)
        speed_px_s = dist_px / dt

        heading_deg = 0.0
        if dist_px > 1.0:
            rad = math.atan2(dy, dx)
            heading_deg = (math.degrees(rad) + 360.0) % 360.0

        return KinematicState(
            speed_value=round(speed_px_s, 2),
            speed_unit="px/s",
            velocity_mps=None,
            velocity_kmh=None,
            acceleration_mps2=None,
            world_pos=None,
            heading_deg=round(heading_deg, 1),
            distance_increment_m=0.0,
            is_calibrated=False,
            quality_assessment=KinematicQualityAssessor.assess(
                is_calibrated=False,
                history_length=history_length,
                dt=dt,
                speed_mps=None,
                accel_mps2=None,
            ),
        )


class GroundPlaneSpeedEstimator(BaseSpeedEstimator):
    """
    Mode 2: Real-World Metric Ground Kinematics (m/s, km/h, m/s², world X/Y in meters).
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

    def estimate_kinematics(
        self,
        current_bbox: List[float],
        prev_bbox: Optional[List[float]],
        dt: float,
        prev_velocity_mps: Optional[float] = None,
        history_length: int = 1,
    ) -> KinematicState:
        if not self.homography.is_calibrated:
            return self.fallback.estimate_kinematics(
                current_bbox, prev_bbox, dt, prev_velocity_mps, history_length
            )

        dt = max(0.001, dt)
        g_curr = self.homography.transform_ground_contact(current_bbox)

        if g_curr is None:
            return self.fallback.estimate_kinematics(
                current_bbox, prev_bbox, dt, prev_velocity_mps, history_length
            )

        if prev_bbox is None:
            return KinematicState(
                speed_value=0.0,
                speed_unit="km/h",
                velocity_mps=0.0,
                velocity_kmh=0.0,
                acceleration_mps2=0.0,
                world_pos=(round(g_curr[0], 2), round(g_curr[1], 2)),
                heading_deg=0.0,
                distance_increment_m=0.0,
                is_calibrated=True,
                quality_assessment=KinematicQualityAssessor.assess(
                    is_calibrated=True,
                    history_length=history_length,
                    dt=dt,
                    speed_mps=0.0,
                    accel_mps2=0.0,
                ),
            )

        g_prev = self.homography.transform_ground_contact(prev_bbox)
        if g_prev is None:
            return self.fallback.estimate_kinematics(
                current_bbox, prev_bbox, dt, prev_velocity_mps, history_length
            )

        # Metric displacement in ground plane meters
        dx_m = g_curr[0] - g_prev[0]
        dy_m = g_curr[1] - g_prev[1]
        dist_m = math.hypot(dx_m, dy_m)

        # Derived velocity in m/s and km/h
        speed_m_s = dist_m / dt
        speed_km_h = speed_m_s * 3.6

        # Derived acceleration in m/s²
        accel_m_s2: Optional[float] = None
        if prev_velocity_mps is not None:
            accel_m_s2 = (speed_m_s - prev_velocity_mps) / dt

        # Metric heading in degrees [0, 360)
        heading_deg = 0.0
        if dist_m > 0.05:
            rad = math.atan2(dy_m, dx_m)
            heading_deg = (math.degrees(rad) + 360.0) % 360.0

        # Assess kinematics quality and detect teleportation/jumps
        assessment = KinematicQualityAssessor.assess(
            is_calibrated=True,
            history_length=history_length,
            dt=dt,
            speed_mps=speed_m_s,
            accel_mps2=accel_m_s2,
        )

        return KinematicState(
            speed_value=round(speed_km_h, 1),
            speed_unit="km/h",
            velocity_mps=round(speed_m_s, 2),
            velocity_kmh=round(speed_km_h, 1),
            acceleration_mps2=round(accel_m_s2, 2) if accel_m_s2 is not None else None,
            world_pos=(round(g_curr[0], 2), round(g_curr[1], 2)),
            heading_deg=round(heading_deg, 1),
            distance_increment_m=round(dist_m, 2),
            is_calibrated=True,
            quality_assessment=assessment,
        )
