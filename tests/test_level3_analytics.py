"""
Automated Unit & Integration Tests for Level 3 Aggregate Traffic Analytics Engine
Tests:
  1. Top 6 Operational KPIs computation
  2. Traffic Flow Timeline time binning and peak detection
  3. 12-Directional Intersection Movement classification
  4. Lane / Corridor volume aggregation and modal splits
  5. Modal Split distribution
  6. Queue Evolution time-series tracking
  7. Origin-Destination 4x4 matrix computation
  8. Flow-Density scatter points and regime classification
"""

import pytest
from backend.analytics.level3_engine import Level3AnalyticsEngine
from backend.trajectories.models import TrackTrajectory, TrajectoryPoint
from backend.perception.classification.taxonomy import RoadUserClass


def make_mock_trajectory(
    track_id: int,
    cls: RoadUserClass = RoadUserClass.CAR,
    fine_cls: str = "Sedan",
    first_seen: float = 0.0,
    last_seen: float = 10.0,
    start_pos: tuple = (100.0, 100.0),
    end_pos: tuple = (1800.0, 950.0),
    velocity_kmh: float = 45.0,
    heading: float = 45.0,
) -> TrackTrajectory:
    """Helper to generate realistic test trajectory."""
    t = TrackTrajectory(
        track_id=track_id,
        raw_class=cls.value.lower(),
        normalized_class=cls,
        fine_grained_class=fine_cls,
        confidence=0.92,
        first_seen=first_seen,
        last_seen=last_seen,
        first_frame=int(first_seen * 30),
        last_frame=int(last_seen * 30),
        total_frames=int((last_seen - first_seen) * 30),
        is_active=True,
        is_uncertain=False,
        current_bbox=[end_pos[0]-20, end_pos[1]-20, end_pos[0]+20, end_pos[1]+20],
        current_centroid=end_pos,
        current_speed=velocity_kmh / 0.234,
        current_heading=heading,
        current_velocity_kmh=velocity_kmh,
        current_velocity_mps=velocity_kmh / 3.6,
        current_acceleration_mps2=0.5,
        is_calibrated=True,
    )
    # Add start point
    t.history.append(TrajectoryPoint(
        frame_index=int(first_seen * 30),
        timestamp=first_seen,
        bbox=[start_pos[0]-20, start_pos[1]-20, start_pos[0]+20, start_pos[1]+20],
        centroid=start_pos,
        velocity=(10.0, 10.0),
        speed_estimate=velocity_kmh / 0.234,
        heading=heading,
        confidence=0.92,
        velocity_kmh=velocity_kmh,
        velocity_mps=velocity_kmh / 3.6,
        acceleration_mps2=0.5,
    ))
    # Add end point
    t.history.append(TrajectoryPoint(
        frame_index=int(last_seen * 30),
        timestamp=last_seen,
        bbox=[end_pos[0]-20, end_pos[1]-20, end_pos[0]+20, end_pos[1]+20],
        centroid=end_pos,
        velocity=(10.0, 10.0),
        speed_estimate=velocity_kmh / 0.234,
        heading=heading,
        confidence=0.92,
        velocity_kmh=velocity_kmh,
        velocity_mps=velocity_kmh / 3.6,
        acceleration_mps2=0.5,
    ))
    return t


def test_level3_kpi_computation():
    """Verify computation of Top 6 operational KPIs."""
    engine = Level3AnalyticsEngine(frame_width=1920, frame_height=1080)

    # Create mixed traffic dataset
    trajectories = [
        make_mock_trajectory(1, RoadUserClass.CAR, "Sedan", 0.0, 15.0, (200, 200), (1600, 200), 50.0),
        make_mock_trajectory(2, RoadUserClass.MOTORCYCLE, "Motorcycle", 2.0, 18.0, (200, 800), (1600, 800), 40.0),
        make_mock_trajectory(3, RoadUserClass.BUS, "Bus", 5.0, 25.0, (960, 100), (960, 950), 30.0),
        make_mock_trajectory(4, RoadUserClass.HGV, "Truck", 0.0, 30.0, (960, 950), (960, 100), 25.0),
        # Stopped/slow queue vehicle
        make_mock_trajectory(5, RoadUserClass.CAR, "Hatchback", 10.0, 30.0, (500, 500), (510, 510), 3.0),
    ]

    res = engine.compute_macro_analytics(trajectories, time_range="all")

    assert res["status"] == "SUCCESS"
    kpis = res["kpis"]

    # Flow should be positive (> 0 vpm)
    assert kpis["total_flow_vpm"] > 0.0
    # Avg speed should reflect active vehicles
    assert 20.0 <= kpis["average_speed_kmh"] <= 60.0
    # Density should be computed in veh/km
    assert kpis["traffic_density_vpk"] > 0.0
    # Road occupancy percentage should be between 0 and 100%
    assert 0.0 <= kpis["road_occupancy_pct"] <= 100.0
    # Active queue should detect slow vehicle
    assert kpis["active_queue_meters"] >= 6.5
    # Peak flow should be recorded
    assert kpis["peak_flow_vpm"] > 0.0


def test_level3_flow_timeline():
    """Verify temporal flow binning and category breakdown."""
    engine = Level3AnalyticsEngine(frame_width=1920, frame_height=1080)

    trajectories = [
        make_mock_trajectory(1, RoadUserClass.CAR, "Sedan", 0.0, 10.0),
        make_mock_trajectory(2, RoadUserClass.CAR, "SUV", 2.0, 8.0),
        make_mock_trajectory(3, RoadUserClass.MOTORCYCLE, "Scooter", 5.0, 15.0),
        make_mock_trajectory(4, RoadUserClass.BUS, "Bus", 10.0, 25.0),
    ]

    res = engine.compute_macro_analytics(trajectories, time_range="all")
    timeline = res["flow_timeline"]

    assert len(timeline["bins"]) >= 2
    assert timeline["peak_flow_vpm"] > 0.0

    first_bin = timeline["bins"][0]
    assert "cars" in first_bin
    assert "motorcycles" in first_bin
    assert "buses" in first_bin
    assert "flow_vpm" in first_bin


def test_level3_12_movements():
    """Verify 12-directional intersection movement counts."""
    engine = Level3AnalyticsEngine(frame_width=1920, frame_height=1080)

    # North to South (top center to bottom center)
    t_ns = make_mock_trajectory(1, RoadUserClass.CAR, "Sedan", 0.0, 10.0, (960, 50), (960, 1020))
    # West to East (left center to right center)
    t_we = make_mock_trajectory(2, RoadUserClass.CAR, "Sedan", 0.0, 10.0, (50, 540), (1870, 540))

    res = engine.compute_macro_analytics([t_ns, t_we], time_range="all")
    movements = res["movements"]

    assert len(movements) == 12
    m_dict = {m["movement"]: m["count"] for m in movements}

    assert m_dict["N → S"] >= 1
    assert m_dict["W → E"] >= 1


def test_level3_origin_destination_matrix():
    """Verify 4x4 Origin-Destination matrix calculation."""
    engine = Level3AnalyticsEngine(frame_width=1920, frame_height=1080)

    t1 = make_mock_trajectory(1, RoadUserClass.CAR, "Sedan", 0.0, 10.0, (960, 50), (960, 1020))  # N -> S
    t2 = make_mock_trajectory(2, RoadUserClass.CAR, "SUV", 0.0, 10.0, (50, 540), (1870, 540))   # W -> E

    res = engine.compute_macro_analytics([t1, t2], time_range="all")
    od_matrix = res["od_matrix"]

    assert len(od_matrix) == 4  # N, S, E, W rows
    n_row = next(r for r in od_matrix if r["origin"] == "N")
    assert n_row["destinations"]["S"]["count"] == 1


def test_level3_flow_density_relationship():
    """Verify Flow-Density relationship scatter points and regimes."""
    engine = Level3AnalyticsEngine(frame_width=1920, frame_height=1080)

    trajectories = [
        make_mock_trajectory(i, RoadUserClass.CAR, "Sedan", 0.0, 20.0, velocity_kmh=45.0)
        for i in range(1, 10)
    ]

    res = engine.compute_macro_analytics(trajectories, time_range="all")
    fd = res["flow_density"]

    assert len(fd["points"]) >= 1
    for p in fd["points"]:
        assert "density_vpk" in p
        assert "flow_vpm" in p
        assert p["regime"] in ["FREE_FLOW", "HIGH_FLOW", "CONGESTED"]
