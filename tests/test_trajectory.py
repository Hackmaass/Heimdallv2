"""
Unit Tests for Trajectory Engine, SQLite Persistence & Exporters
"""

import os
import json
import pytest
from backend.trajectories.engine import TrajectoryEngine
from backend.trajectories.storage import TrajectoryStorage
from backend.perception.tracking.base import TrackedObject
from backend.perception.classification.taxonomy import normalize_class


def test_trajectory_engine_and_storage(tmp_path):
    db_path = str(tmp_path / "test_heimdall.db")
    storage = TrajectoryStorage(db_path=db_path)
    engine = TrajectoryEngine(storage=storage)

    # Frame 0
    norm1 = normalize_class("car", 0.90)
    obj1 = TrackedObject(
        track_id=1,
        raw_class="car",
        normalized=norm1,
        confidence=0.90,
        bbox=[100, 100, 150, 150],
        centroid=(125, 125),
        velocity=(0, 0),
        speed_estimate=0.0,
        heading=0.0,
    )

    trajs = engine.update_tracks([obj1], frame_index=0, timestamp=0.0)
    assert len(trajs) == 1
    assert trajs[0].track_id == 1
    assert trajs[0].total_frames == 1

    # Frame 1 (Moving)
    obj1_next = TrackedObject(
        track_id=1,
        raw_class="car",
        normalized=norm1,
        confidence=0.92,
        bbox=[130, 140, 180, 190],
        centroid=(155, 165),
        velocity=(30, 40),
        speed_estimate=50.0,
        heading=53.1,
    )

    trajs = engine.update_tracks([obj1_next], frame_index=1, timestamp=1.0)
    assert trajs[0].total_frames == 2
    assert len(trajs[0].history) == 2
    assert trajs[0].duration_seconds == 1.0

    # Persist
    engine.persist_all(session_id="test_session")
    tracks_in_db = storage.get_all_tracks()
    assert len(tracks_in_db) == 1
    assert tracks_in_db[0]["track_id"] == 1
    assert tracks_in_db[0]["normalized_class"] == "CAR"

    # Test Exporters
    jsonl_file = str(tmp_path / "tracks.jsonl")
    csv_file = str(tmp_path / "tracks.csv")
    traj_file = str(tmp_path / "trajectories.json")
    summary_file = str(tmp_path / "summary.json")

    storage.export_jsonl(trajs, jsonl_file)
    storage.export_csv(trajs, csv_file)
    storage.export_trajectories_json(trajs, traj_file)
    summary = storage.export_summary_json("test_vid", duration=2.0, total_frames=2, tracks=trajs, filepath=summary_file)

    assert os.path.exists(jsonl_file)
    assert os.path.exists(csv_file)
    assert os.path.exists(traj_file)
    assert os.path.exists(summary_file)
    assert summary["total_unique_tracks"] == 1
    assert summary["class_counts"]["CAR"] == 1
