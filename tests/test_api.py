"""
Unit Tests for FastAPI REST Endpoints
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "compute" in data


def test_api_tracks():
    res = client.get("/api/tracks")
    assert res.status_code == 200
    data = res.json()
    assert "tracks" in data
    assert "total" in data


def test_api_telemetry():
    res = client.get("/api/telemetry")
    assert res.status_code == 200
    data = res.json()
    assert "position" in data
    assert "battery_pct" in data


def test_api_flytbase_status():
    res = client.get("/api/flytbase/status")
    assert res.status_code == 200
    data = res.json()
    assert "vehicle_state" in data
    assert "mode" in data


def test_api_videos_and_static():
    res = client.get("/api/videos")
    assert res.status_code == 200
    data = res.json()
    assert "videos" in data

    # Verify placeholder static asset returns 200
    res_static = client.get("/static/placeholder.jpg")
    assert res_static.status_code == 200


def test_api_calibration_status():
    res = client.get("/api/calibration")
    assert res.status_code == 200
    data = res.json()
    assert "is_calibrated" in data
    assert "has_srt_telemetry" in data


def test_api_video_process_and_status():
    # Enqueue a processing request
    res = client.post(
        "/api/video/process",
        json={
            "video_path": "data/Multi_Road_Merged_convert_4k.mp4",
            "model_name": "yolov8n.pt",
            "tracker_type": "botsort",
            "max_frames": 2,
            "save_annotated_video": False,
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert "video_id" in data
    assert data["status"] in ("QUEUED", "PROCESSING", "COMPLETED")

    # Poll status
    job_id = data["video_id"]
    res_status = client.get(f"/api/video/{job_id}/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["video_id"] == job_id
    assert "progress_percent" in status_data
