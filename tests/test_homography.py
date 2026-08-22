"""
Unit Tests for Level 2 Ground-Plane Perspective Homography Calibration
"""

import pytest
import numpy as np
from backend.trajectories.homography import RoadPlaneHomography


def test_homography_calibration_from_dimensions():
    # 4 points defining a road quadrilateral in an aerial perspective
    image_points = [
        [500.0, 300.0],   # P0: Top-Left
        [700.0, 300.0],   # P1: Top-Right
        [850.0, 900.0],   # P2: Bottom-Right
        [350.0, 900.0],   # P3: Bottom-Left
    ]
    road_width_m = 7.5
    road_length_m = 30.0

    h = RoadPlaneHomography()
    success = h.calibrate_from_dimensions(image_points, road_width_m, road_length_m)

    assert success is True
    assert h.is_calibrated is True
    assert h.matrix is not None
    assert h.rms_error_m >= 0.0

    # Transform Bottom-Left point (should map close to (0.0, 0.0))
    p3_ground = h.transform_point((350.0, 900.0))
    assert p3_ground is not None
    assert abs(p3_ground[0] - 0.0) < 0.1
    assert abs(p3_ground[1] - 0.0) < 0.1

    # Transform Bottom-Right point (should map close to (7.5, 0.0))
    p2_ground = h.transform_point((850.0, 900.0))
    assert p2_ground is not None
    assert abs(p2_ground[0] - 7.5) < 0.1
    assert abs(p2_ground[1] - 0.0) < 0.1

    # Transform Top-Left point (should map close to (0.0, 30.0))
    p0_ground = h.transform_point((500.0, 300.0))
    assert p0_ground is not None
    assert abs(p0_ground[0] - 0.0) < 0.1
    assert abs(p0_ground[1] - 30.0) < 0.1


def test_ground_contact_transform():
    h = RoadPlaneHomography()
    image_points = [
        [100.0, 100.0],
        [300.0, 100.0],
        [300.0, 500.0],
        [100.0, 500.0],
    ]
    h.calibrate_from_dimensions(image_points, 10.0, 20.0)

    # Vehicle bounding box [x1, y1, x2, y2]
    # Centroid: (200, 300), Ground contact (bottom center): (200, 500)
    bbox = [150.0, 200.0, 250.0, 500.0]
    g_pt = h.transform_ground_contact(bbox)

    assert g_pt is not None
    # Ground contact at y=500 should have ground Y = 0.0
    assert abs(g_pt[1] - 0.0) < 0.1
    # x=200 is midpoint -> ground X = 5.0
    assert abs(g_pt[0] - 5.0) < 0.1
