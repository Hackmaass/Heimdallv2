"""
Unit Tests for Pixel and Ground Plane Speed Estimation
"""

import pytest
from backend.trajectories.speed_estimator import (
    PixelSpeedEstimator,
    GroundPlaneSpeedEstimator,
)
from backend.trajectories.homography import RoadPlaneHomography


def test_pixel_speed_estimator():
    estimator = PixelSpeedEstimator()
    # Moving (100, 100) -> (130, 140) over 1.0 second: dx=30, dy=40, dist=50px
    res = estimator.estimate((130, 140), (100, 100), dt=1.0)
    assert res.value == 50.0
    assert res.unit == "px/s"
    assert res.is_calibrated is False
    assert res.label == "Relative speed"


def test_ground_plane_speed_estimator():
    # 4 image points to 4 ground meter points (100px = 10 meters, so 1px = 0.1m)
    img_pts = [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]
    world_pts = [(0, 0), (100, 0), (100, 100), (0, 100)]  # 100m x 100m

    homography = RoadPlaneHomography(img_pts, world_pts)
    assert homography.is_calibrated is True

    estimator = GroundPlaneSpeedEstimator(homography)

    # Move 100 pixels in 1 second = 10 meters in 1 second = 36 km/h
    res = estimator.estimate((100, 0), (0, 0), dt=1.0)
    assert res.is_calibrated is True
    assert res.unit == "km/h"
    assert pytest.approx(res.value, 0.1) == 36.0
