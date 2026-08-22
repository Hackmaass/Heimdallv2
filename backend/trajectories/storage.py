"""
Trajectory Storage & Exporters (SQLite + JSONL / CSV / JSON)
Designed with a schema clean and ready for PostgreSQL / PostGIS migration.
"""

import sqlite3
import json
import csv
import os
from typing import List, Dict, Any, Optional
from .models import TrackTrajectory, TrajectoryPoint
from ..perception.classification.taxonomy import RoadUserClass


class TrajectoryStorage:
    """
    Relational SQLite persistence engine and structured file exporter.
    """

    def __init__(self, db_path: str = "outputs/heimdall.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def clear_all(self) -> None:
        """Clears all stored tracks and trajectory points from SQLite."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM heimdall_trajectory_points")
            cursor.execute("DELETE FROM heimdall_tracks")
            conn.commit()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Video sessions / jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS heimdall_sessions (
                    session_id TEXT PRIMARY KEY,
                    filename TEXT,
                    duration_seconds REAL,
                    total_frames INTEGER,
                    total_tracks INTEGER,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tracks summary table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS heimdall_tracks (
                    track_id INTEGER PRIMARY KEY,
                    session_id TEXT,
                    raw_class TEXT NOT NULL,
                    normalized_class TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    first_frame INTEGER NOT NULL,
                    last_frame INTEGER NOT NULL,
                    total_frames INTEGER NOT NULL,
                    is_uncertain BOOLEAN NOT NULL,
                    average_speed REAL NOT NULL,
                    total_distance_px REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Per-frame trajectory observations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS heimdall_trajectory_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id INTEGER NOT NULL,
                    frame_index INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    x1 REAL NOT NULL,
                    y1 REAL NOT NULL,
                    x2 REAL NOT NULL,
                    y2 REAL NOT NULL,
                    cx REAL NOT NULL,
                    cy REAL NOT NULL,
                    vx REAL NOT NULL,
                    vy REAL NOT NULL,
                    speed REAL NOT NULL,
                    heading REAL NOT NULL,
                    confidence REAL NOT NULL,
                    FOREIGN KEY (track_id) REFERENCES heimdall_tracks (track_id)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_point_track ON heimdall_trajectory_points (track_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_point_frame ON heimdall_trajectory_points (frame_index)")
            conn.commit()

    def save_track(self, track: TrackTrajectory, session_id: Optional[str] = None) -> None:
        """Saves or updates a track and appends its latest points."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO heimdall_tracks (
                    track_id, session_id, raw_class, normalized_class, confidence,
                    first_seen, last_seen, first_frame, last_frame, total_frames,
                    is_uncertain, average_speed, total_distance_px
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    last_frame = excluded.last_frame,
                    total_frames = excluded.total_frames,
                    average_speed = excluded.average_speed,
                    total_distance_px = excluded.total_distance_px
            """, (
                track.track_id,
                session_id,
                track.raw_class,
                track.normalized_class.value,
                track.confidence,
                track.first_seen,
                track.last_seen,
                track.first_frame,
                track.last_frame,
                track.total_frames,
                1 if track.is_uncertain else 0,
                track.average_speed,
                track.total_distance_pixels,
            ))
            conn.commit()

    def save_trajectory_point(self, track_id: int, pt: TrajectoryPoint) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO heimdall_trajectory_points (
                    track_id, frame_index, timestamp,
                    x1, y1, x2, y2, cx, cy, vx, vy, speed, heading, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                track_id,
                pt.frame_index,
                pt.timestamp,
                pt.bbox[0], pt.bbox[1], pt.bbox[2], pt.bbox[3],
                pt.centroid[0], pt.centroid[1],
                pt.velocity[0], pt.velocity[1],
                pt.speed_estimate,
                pt.heading,
                pt.confidence,
            ))
            conn.commit()

    def get_all_tracks(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute("SELECT * FROM heimdall_tracks WHERE session_id = ?", (session_id,))
            else:
                cursor.execute("SELECT * FROM heimdall_tracks ORDER BY track_id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_track(self, track_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM heimdall_tracks WHERE track_id = ?", (track_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_trajectory_points(self, track_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM heimdall_trajectory_points
                WHERE track_id = ? ORDER BY frame_index ASC
            """, (track_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_all_trajectories_with_trails(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches all stored tracks and builds coordinate trails for 2D visualizer."""
        tracks = self.get_all_tracks(session_id=session_id)
        result = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for t in tracks:
                cursor.execute("""
                    SELECT frame_index, timestamp, cx, cy, speed, heading, confidence, x1, y1, x2, y2
                    FROM heimdall_trajectory_points
                    WHERE track_id = ? ORDER BY frame_index ASC
                """, (t["track_id"],))
                pts = [dict(r) for r in cursor.fetchall()]
                trail = [[p["cx"], p["cy"]] for p in pts]
                centroid = trail[-1] if trail else [0, 0]
                result.append({
                    "id": t["track_id"],
                    "class": t["normalized_class"],
                    "raw_class": t["raw_class"],
                    "confidence": t["confidence"],
                    "is_uncertain": bool(t["is_uncertain"]),
                    "speed": t["average_speed"],
                    "heading": pts[-1]["heading"] if pts else 0.0,
                    "centroid": centroid,
                    "bbox": [pts[-1]["x1"], pts[-1]["y1"], pts[-1]["x2"], pts[-1]["y2"]] if pts else [0, 0, 0, 0],
                    "trail": trail,
                    "duration": round(t["last_seen"] - t["first_seen"], 1),
                    "total_frames": t["total_frames"],
                    "total_distance_px": t["total_distance_px"],
                })
        return result

    # ── Exporters ─────────────────────────────────────────────────────────────

    def export_jsonl(self, tracks: List[TrackTrajectory], filepath: str) -> None:
        """Exports every per-frame observation to JSON Lines (JSONL)."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            for track in tracks:
                for pt in track.history:
                    line = {
                        "frame_index": pt.frame_index,
                        "timestamp": round(pt.timestamp, 3),
                        "track_id": track.track_id,
                        "raw_class": track.raw_class,
                        "normalized_class": track.normalized_class.value,
                        "confidence": round(pt.confidence, 3),
                        "bbox": [round(v, 1) for v in pt.bbox],
                        "centroid": [round(v, 1) for v in pt.centroid],
                        "velocity": [round(v, 2) for v in pt.velocity],
                        "speed": round(pt.speed_estimate, 2),
                        "heading": round(pt.heading, 1),
                        "is_uncertain": track.is_uncertain,
                        "first_seen": round(track.first_seen, 3),
                        "last_seen": round(track.last_seen, 3),
                    }
                    f.write(json.dumps(line) + "\n")

    def export_csv(self, tracks: List[TrackTrajectory], filepath: str) -> None:
        """Exports per-frame observations to CSV."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        fieldnames = [
            "frame_index", "timestamp", "track_id", "raw_class", "normalized_class",
            "confidence", "x1", "y1", "x2", "y2", "cx", "cy", "vx", "vy",
            "speed", "heading", "is_uncertain", "first_seen", "last_seen"
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for track in tracks:
                for pt in track.history:
                    writer.writerow({
                        "frame_index": pt.frame_index,
                        "timestamp": round(pt.timestamp, 3),
                        "track_id": track.track_id,
                        "raw_class": track.raw_class,
                        "normalized_class": track.normalized_class.value,
                        "confidence": round(pt.confidence, 3),
                        "x1": round(pt.bbox[0], 1),
                        "y1": round(pt.bbox[1], 1),
                        "x2": round(pt.bbox[2], 1),
                        "y2": round(pt.bbox[3], 1),
                        "cx": round(pt.centroid[0], 1),
                        "cy": round(pt.centroid[1], 1),
                        "vx": round(pt.velocity[0], 2),
                        "vy": round(pt.velocity[1], 2),
                        "speed": round(pt.speed_estimate, 2),
                        "heading": round(pt.heading, 1),
                        "is_uncertain": 1 if track.is_uncertain else 0,
                        "first_seen": round(track.first_seen, 3),
                        "last_seen": round(track.last_seen, 3),
                    })

    def export_trajectories_json(self, tracks: List[TrackTrajectory], filepath: str) -> None:
        """Exports full hierarchical trajectory history to JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        data = []
        for track in tracks:
            item = track.to_dict()
            item["trail"] = [
                {
                    "frame": p.frame_index,
                    "t": round(p.timestamp, 3),
                    "cx": round(p.centroid[0], 1),
                    "cy": round(p.centroid[1], 1),
                    "speed": round(p.speed_estimate, 2),
                    "heading": round(p.heading, 1),
                }
                for p in track.history
            ]
            data.append(item)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def export_summary_json(
        self,
        video_id: str,
        duration: float,
        total_frames: int,
        tracks: List[TrackTrajectory],
        filepath: str,
    ) -> Dict[str, Any]:
        """Generates summary.json containing high-level analytics and class breakdown."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

        class_counts: Dict[str, int] = {c.value: 0 for c in RoadUserClass}
        active_count = sum(1 for t in tracks if t.is_active)
        speeds = [t.average_speed for t in tracks if t.average_speed > 0]
        avg_speed = float(sum(speeds) / len(speeds)) if speeds else 0.0

        for t in tracks:
            cls_key = t.normalized_class.value
            class_counts[cls_key] = class_counts.get(cls_key, 0) + 1

        summary = {
            "video_id": video_id,
            "duration_seconds": round(duration, 2),
            "total_frames_processed": total_frames,
            "total_unique_tracks": len(tracks),
            "active_tracks_at_end": active_count,
            "average_traffic_speed": round(avg_speed, 2),
            "class_counts": class_counts,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        return summary
