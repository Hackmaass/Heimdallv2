"""
Unit Tests for Level 4 Spatial Grounding, Georeferencing, Map Matching, and APIs
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.spatial import (
    SpatialGeoreferencer,
    SpatialConfidenceFlag,
    RoadNetwork,
    create_default_intersection_network,
    MapMatcher,
    Level4SpatialEngine,
)
from backend.trajectories.models import TrackTrajectory, TrajectoryPoint
from backend.perception.classification.taxonomy import RoadUserClass


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_trajectory():
    """Generates a synthetic vehicle trajectory moving from East approach to West across intersection."""
    pts = []
    # 20 frames moving from pixel (1600, 540) to (300, 540) in 1920x1080 image
    for i in range(20):
        t = i * 0.1
        u = 1600.0 - i * 65.0
        v = 540.0
        pts.append(
            TrajectoryPoint(
                frame_index=i,
                timestamp=t,
                bbox=[u - 20, v - 10, u + 20, v + 10],
                centroid=(u, v),
                velocity=(-650.0, 0.0),
                speed_estimate=35.0,
                heading=270.0,  # Heading West
                confidence=0.92,
                velocity_kmh=35.0,
                acceleration_mps2=0.0,
                fine_grained_class="Car",
            )
        )

    return TrackTrajectory(
        track_id=128,
        raw_class="car",
        normalized_class=RoadUserClass.CAR,
        confidence=0.92,
        first_seen=0.0,
        last_seen=1.9,
        first_frame=0,
        last_frame=19,
        total_frames=20,
        is_active=True,
        is_uncertain=False,
        current_bbox=[300 - 20, 540 - 10, 300 + 20, 540 + 10],
        current_centroid=(300.0, 540.0),
        current_speed=35.0,
        current_heading=270.0,
        fine_grained_class="Car",
        current_velocity_kmh=35.0,
        current_acceleration_mps2=0.0,
        is_calibrated=True,
        history=pts,
    )


def test_meters_per_degree_wgs84():
    """Validates WGS-84 metric conversion accuracy."""
    m_lat, m_lon = SpatialGeoreferencer.meters_per_degree(18.566227)
    assert 110000.0 < m_lat < 112000.0
    assert 104000.0 < m_lon < 106000.0

    # Round trip test
    ref_lat, ref_lon = 18.566227, 73.771846
    target_lat, target_lon = SpatialGeoreferencer.metric_to_wgs84(ref_lat, ref_lon, 50.0, -30.0)
    dx, dy = SpatialGeoreferencer.wgs84_to_metric(ref_lat, ref_lon, target_lat, target_lon)
    assert abs(dx - 50.0) < 0.1
    assert abs(dy - (-30.0)) < 0.1


def test_georeferencer_projection():
    """Validates camera-to-ground pixel georeferencing."""
    georef = SpatialGeoreferencer(anchor_lat=18.566227, anchor_lon=73.771846, is_homography_calibrated=True)
    pt = georef.project_pixel_to_wgs84(960, 540, image_width=1920, image_height=1080)
    assert abs(pt.latitude - 18.566227) < 0.001
    assert abs(pt.longitude - 73.771846) < 0.001
    assert pt.confidence_flag == SpatialConfidenceFlag.CALIBRATED.value


def test_road_network_topology():
    """Validates road network topology and GeoJSON export."""
    net = create_default_intersection_network()
    assert net.intersection is not None
    assert len(net.segments) == 4
    assert len(net.lanes) == 8

    geojson = net.to_geojson()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 1 + 4 + 8  # junction + 4 segments + 8 lanes


def test_map_matcher_directional_continuity():
    """Validates map matching with directional alignment."""
    net = create_default_intersection_network()
    matcher = MapMatcher(net)

    # Point on East approach heading West (bearing 270°)
    ref_lat = net.intersection.center_coord[1]
    ref_lon = net.intersection.center_coord[0] + (50.0 / 105420.0)

    res = matcher.match_point(
        lat=ref_lat + (3.5 / 111132.95),
        lon=ref_lon,
        heading_deg=270.0,
        speed_kmh=35.0,
    )
    assert res.matched is True
    assert res.road_segment_id == "SEG_EAST_IN"
    assert res.approach == "East Approach"
    assert "East" in res.road_name
    assert res.queue_state == "FREE_FLOW"

    # Queued point (< 6 km/h)
    res_queued = matcher.match_point(
        lat=ref_lat + (3.5 / 111132.95),
        lon=ref_lon,
        heading_deg=270.0,
        speed_kmh=3.5,
    )
    assert res_queued.queue_state == "QUEUED"


def test_level4_engine_computations(sample_trajectory):
    """Validates Level 4 spatial analytics calculations."""
    engine = Level4SpatialEngine()
    payload = engine.compute_level4_analytics([sample_trajectory])

    assert "summary_kpis" in payload
    assert payload["summary_kpis"]["total_grounded_vehicles"] == 1
    assert len(payload["grounded_trajectories"]) == 1

    gt = payload["grounded_trajectories"][0]
    assert gt["track_id"] == 128
    assert len(gt["gps_trail"]) == 20
    assert gt["latitude"] > 0.0
    assert gt["longitude"] > 0.0

    assert "desire_lines" in payload
    assert len(payload["desire_lines"]) == 12

    assert "lane_metrics" in payload
    assert len(payload["lane_metrics"]) == 8

    assert "spatial_queues" in payload
    assert len(payload["spatial_queues"]) == 4

    assert "geojson" in payload
    assert payload["geojson"]["type"] == "FeatureCollection"


def test_level4_api_routes(client):
    """Validates Level 4 REST API endpoints."""
    res = client.get("/api/analytics/level4")
    assert res.status_code == 200
    data = res.json()
    assert "summary_kpis" in data
    assert "grounded_trajectories" in data
    assert "desire_lines" in data
    assert "lane_metrics" in data
    assert "spatial_queues" in data
    assert "geojson" in data

    # GeoJSON export
    res_geo = client.get("/api/export/geojson")
    assert res_geo.status_code == 200
    assert res_geo.headers["content-type"].startswith("application/geo+json")

    # Spatial CSV export
    res_csv = client.get("/api/export/spatial-csv")
    assert res_csv.status_code == 200
    assert res_csv.headers["content-type"].startswith("text/csv")
    assert "track_id,vehicle_class" in res_csv.text

    # Road Network endpoint
    res_net = client.get("/api/spatial/road-network")
    assert res_net.status_code == 200
    assert res_net.json()["type"] == "FeatureCollection"
