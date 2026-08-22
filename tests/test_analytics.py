"""
Unit Tests for Traffic Analytics Engine
"""

import pytest
from backend.analytics.engine import TrafficAnalyticsEngine
from backend.trajectories.models import TrackTrajectory, TrajectoryPoint
from backend.perception.classification.taxonomy import RoadUserClass


def test_traffic_analytics_metrics():
    engine = TrafficAnalyticsEngine(frame_width=1920, frame_height=1080)

    # Mock active tracks
    t1 = TrackTrajectory(
        track_id=1,
        raw_class="car",
        normalized_class=RoadUserClass.CAR,
        confidence=0.9,
        first_seen=0.0,
        last_seen=5.0,
        first_frame=0,
        last_frame=50,
        total_frames=51,
        is_active=True,
        is_uncertain=False,
        current_bbox=[100, 100, 150, 150],
        current_centroid=(125, 125),
        current_speed=15.0,
        current_heading=90.0,
    )
    t2 = TrackTrajectory(
        track_id=2,
        raw_class="motorcycle",
        normalized_class=RoadUserClass.MOTORCYCLE,
        confidence=0.85,
        first_seen=1.0,
        last_seen=5.0,
        first_frame=10,
        last_frame=50,
        total_frames=41,
        is_active=True,
        is_uncertain=False,
        current_bbox=[200, 200, 230, 230],
        current_centroid=(215, 215),
        current_speed=25.0,
        current_heading=85.0,
    )

    active = [t1, t2]

    # Class distribution
    dist = engine.calculate_class_distribution(active, active)
    assert dist.counts["CAR"] == 1
    assert dist.counts["MOTORCYCLE"] == 1
    assert dist.total_active == 2

    # Density
    density = engine.calculate_density(active)
    assert density.raw_active_count == 2
    assert density.congestion_level == "LOW"

    # Speed
    speed = engine.calculate_average_speed(active)
    assert speed.average_speed == 20.0
    assert speed.fastest_track_id == 2
    assert speed.fastest_speed == 25.0
