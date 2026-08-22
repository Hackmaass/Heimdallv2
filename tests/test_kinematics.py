"""
Unit Tests for Level 2 Metric Kinematics and Quality Control Flagging
"""

import pytest
from backend.trajectories.homography import RoadPlaneHomography
from backend.trajectories.speed_estimator import GroundPlaneSpeedEstimator, PixelSpeedEstimator
from backend.trajectories.quality import KinematicQualityAssessor, KinematicQualityFlag


def test_metric_velocity_and_acceleration():
    h = RoadPlaneHomography()
    image_points = [
        [100.0, 100.0],
        [300.0, 100.0],
        [300.0, 500.0],
        [100.0, 500.0],
    ]
    # Road size: 10m wide by 50m long
    h.calibrate_from_dimensions(image_points, 10.0, 50.0)

    estimator = GroundPlaneSpeedEstimator(h)

    # Frame 0: Box at y=450 (close to bottom)
    bbox0 = [150.0, 400.0, 250.0, 450.0]
    res0 = estimator.estimate_kinematics(bbox0, None, 0.033, None, history_length=1)
    assert res0.is_calibrated is True
    assert res0.world_pos is not None

    # Frame 1: Box moves to y=448 (moved forward ~0.25m in 0.1s = 2.5 m/s = 9.0 km/h)
    bbox1 = [150.0, 398.0, 250.0, 448.0]
    res1 = estimator.estimate_kinematics(bbox1, bbox0, 0.1, None, history_length=2)

    assert res1.velocity_mps is not None
    assert res1.velocity_mps > 0
    assert res1.velocity_kmh is not None
    assert abs(res1.velocity_kmh - res1.velocity_mps * 3.6) < 0.1
    assert res1.speed_unit == "km/h"

    # Frame 2: Box moves to y=445 (~0.375m in 0.1s = 3.75 m/s = 13.5 km/h, accel = 12.5 m/s²)
    bbox2 = [150.0, 395.0, 250.0, 445.0]
    res2 = estimator.estimate_kinematics(bbox2, bbox1, 0.1, prev_velocity_mps=res1.velocity_mps, history_length=6)
    assert res2.acceleration_mps2 is not None
    assert res2.quality_assessment.flag == KinematicQualityFlag.VALID_HIGH_CONFIDENCE


def test_quality_control_flagging():
    # 1. Uncalibrated
    assessment_uncal = KinematicQualityAssessor.assess(
        is_calibrated=False,
        history_length=10,
        dt=0.033,
        speed_mps=15.0,
        accel_mps2=1.2,
    )
    assert assessment_uncal.flag == KinematicQualityFlag.UNRELIABLE_MISSING_CALIBRATION
    assert assessment_uncal.is_reliable is False

    # 2. Insufficient history (< 5 observations)
    assessment_short = KinematicQualityAssessor.assess(
        is_calibrated=True,
        history_length=2,
        dt=0.033,
        speed_mps=15.0,
        accel_mps2=1.2,
    )
    assert assessment_short.flag == KinematicQualityFlag.UNRELIABLE_INSUFFICIENT_HISTORY

    # 3. Valid high-confidence
    assessment_valid = KinematicQualityAssessor.assess(
        is_calibrated=True,
        history_length=10,
        dt=0.033,
        speed_mps=15.0,
        accel_mps2=1.2,
    )
    assert assessment_valid.flag == KinematicQualityFlag.VALID_HIGH_CONFIDENCE
    assert assessment_valid.is_reliable is True
