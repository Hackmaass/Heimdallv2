"""
Unit Tests for DJI Flight Telemetry SRT Parser & Optical Ground Projection
"""

import os
import pytest
from backend.telemetry.srt_parser import DJISRTParser, SRTTelemetryRecord
from backend.telemetry.srt_provider import SRTTelemetryProvider


def test_parse_multi_road_srt():
    srt_path = os.path.join("data", "Multi_Road_1080p.srt")
    assert os.path.exists(srt_path), f"File {srt_path} must exist"

    parser = DJISRTParser(srt_path)
    assert len(parser.records) > 1000

    rec0 = parser.get_record_by_frame(0)
    assert rec0 is not None
    assert rec0.frame_index == 0
    assert abs(rec0.latitude - 18.566225) < 1e-4
    assert abs(rec0.longitude - 73.771845) < 1e-4
    assert abs(rec0.rel_alt - 70.469) < 0.1
    assert abs(rec0.abs_alt - 607.270) < 0.1
    assert abs(rec0.gb_yaw - (-83.4)) < 0.1
    assert abs(rec0.gb_pitch - (-18.5)) < 0.1
    assert abs(rec0.focal_len - 24.0) < 0.1


def test_parse_intersection_srt():
    srt_path = os.path.join("data", "Intersection_1080p (1).srt")
    assert os.path.exists(srt_path), f"File {srt_path} must exist"

    parser = DJISRTParser(srt_path)
    assert len(parser.records) > 1000

    rec0 = parser.get_record_by_frame(0)
    assert rec0 is not None
    assert rec0.frame_index == 0
    assert abs(rec0.latitude - 18.566227) < 1e-4
    assert abs(rec0.longitude - 73.771846) < 1e-4
    assert abs(rec0.rel_alt - 70.472) < 0.1
    assert abs(rec0.gb_pitch - (-63.1)) < 0.1
    assert abs(rec0.gb_yaw - (-125.5)) < 0.1


def test_ground_projection_and_gsd():
    srt_path = os.path.join("data", "Multi_Road_1080p.srt")
    parser = DJISRTParser(srt_path)

    # 4K image dimensions
    w, h = 3840, 2160

    # Test GSD calculation (meters per pixel)
    gsd = parser.compute_ground_sampling_distance(w, h, frame_index=0)
    assert 0.01 <= gsd <= 0.50  # Realistic drone GSD range (e.g. 5-15 cm/pixel)

    # Test Ground Projection: Image center (w/2, h/2)
    gx, gy = parser.pixel_to_ground_meters(w / 2.0, h / 2.0, w, h, frame_index=0)
    assert isinstance(gx, float)
    assert isinstance(gy, float)

    # Test Homography Matrix Generation
    H = parser.generate_homography_matrix(w, h, frame_index=0)
    assert H.shape == (3, 3)


def test_srt_provider_and_auto_matching():
    video_path = os.path.join("data", "Multi_Road_Merged_convert_4k.mp4")
    matching_srt = SRTTelemetryProvider.find_matching_srt(video_path)

    assert matching_srt is not None
    assert os.path.exists(matching_srt)
    assert "Multi_Road" in matching_srt

    provider = SRTTelemetryProvider(matching_srt)
    assert provider.is_loaded is True

    telemetry = provider.get_telemetry(frame_index=10, timestamp=0.33)
    assert abs(telemetry.latitude - 18.566225) < 1e-4
    assert telemetry.altitude_agl > 50.0
    assert telemetry.flight_mode == "DJI_SRT_LIVE"

    # Test Ground Homography from Provider
    homography = provider.get_ground_homography(3840, 2160, frame_index=10)
    assert homography.is_calibrated is True
    assert homography.matrix is not None
