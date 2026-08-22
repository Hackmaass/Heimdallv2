"""
SQLite Trajectory Persistence & Metric Data Exporters
Level 1 Persistent Storage + Level 2 Extended Kinematic Exports (CSV / JSON)
"""

import sqlite3
import json
import csv
import io
import os
from typing import List, Dict, Any, Optional
from .models import TrackTrajectory, TrajectoryPoint
from ..perception.classification.taxonomy import RoadUserClass


class TrajectoryStorage:
    """
    SQLite & File System Persistence Manager for Tracked Entities & Trajectories.
    """

    def __init__(self, db_path: str = "data/heimdall_trajectories.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS heimdall_sessions (
                    session_id TEXT PRIMARY KEY,
                    video_path TEXT NOT NULL,
                    total_frames INTEGER,
                    fps REAL,
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
                    fine_grained_class TEXT,
                    confidence REAL NOT NULL,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    first_frame INTEGER NOT NULL,
                    last_frame INTEGER NOT NULL,
                    total_frames INTEGER NOT NULL,
                    is_uncertain BOOLEAN NOT NULL,
                    average_speed REAL NOT NULL,
                    total_distance_px REAL NOT NULL,
                    total_distance_m REAL DEFAULT 0.0,
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
                    world_x REAL,
                    world_y REAL,
                    velocity_mps REAL,
                    velocity_kmh REAL,
                    accel_mps2 REAL,
                    quality_flag TEXT,
                    fine_grained_class TEXT,
                    FOREIGN KEY (track_id) REFERENCES heimdall_tracks (track_id)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_point_track ON heimdall_trajectory_points (track_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_point_frame ON heimdall_trajectory_points (frame_index)")
            conn.commit()

    def save_track(self, track: TrackTrajectory, session_id: Optional[str] = None) -> None:
        """Saves or updates a track summary."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO heimdall_tracks (
                    track_id, session_id, raw_class, normalized_class, fine_grained_class, confidence,
                    first_seen, last_seen, first_frame, last_frame, total_frames,
                    is_uncertain, average_speed, total_distance_px, total_distance_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    last_frame = excluded.last_frame,
                    total_frames = excluded.total_frames,
                    fine_grained_class = excluded.fine_grained_class,
                    average_speed = excluded.average_speed,
                    total_distance_px = excluded.total_distance_px,
                    total_distance_m = excluded.total_distance_m
            """, (
                track.track_id,
                session_id,
                track.raw_class,
                track.normalized_class.value,
                track.fine_grained_class,
                track.confidence,
                track.first_seen,
                track.last_seen,
                track.first_frame,
                track.last_frame,
                track.total_frames,
                1 if track.is_uncertain else 0,
                track.average_speed,
                track.total_distance_pixels,
                track.total_distance_meters,
            ))
            conn.commit()

    def save_trajectory_point(self, track_id: int, pt: TrajectoryPoint) -> None:
        """Saves a per-frame trajectory observation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO heimdall_trajectory_points (
                    track_id, frame_index, timestamp,
                    x1, y1, x2, y2, cx, cy, vx, vy, speed, heading, confidence,
                    world_x, world_y, velocity_mps, velocity_kmh, accel_mps2, quality_flag, fine_grained_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                pt.ground_point[0] if pt.ground_point else None,
                pt.ground_point[1] if pt.ground_point else None,
                pt.velocity_mps,
                pt.velocity_kmh,
                pt.acceleration_mps2,
                pt.quality_flag,
                pt.fine_grained_class,
            ))
            conn.commit()

    def get_all_tracks(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute("SELECT * FROM heimdall_tracks WHERE session_id = ? ORDER BY track_id ASC", (session_id,))
            else:
                cursor.execute("SELECT * FROM heimdall_tracks ORDER BY track_id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_all_trajectories_with_trails(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves all tracks with their complete trail coordinates and kinematics."""
        tracks = self.get_all_tracks(session_id)
        result = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for t in tracks:
                cursor.execute("""
                    SELECT frame_index, timestamp, cx, cy, x1, y1, x2, y2, speed, heading,
                           world_x, world_y, velocity_mps, velocity_kmh, accel_mps2, quality_flag, fine_grained_class
                    FROM heimdall_trajectory_points
                    WHERE track_id = ?
                    ORDER BY frame_index ASC
                """, (t["track_id"],))
                pts = cursor.fetchall()
                trail = [[p["cx"], p["cy"]] for p in pts]
                centroid = trail[-1] if trail else [0, 0]
                latest_p = pts[-1] if pts else None

                result.append({
                    "id": t["track_id"],
                    "class": t["normalized_class"],
                    "fine_grained_class": t.get("fine_grained_class") or latest_p["fine_grained_class"] if latest_p else t["normalized_class"],
                    "confidence": t["confidence"],
                    "is_uncertain": bool(t["is_uncertain"]),
                    "speed": t["average_speed"],
                    "velocity_kmh": latest_p["velocity_kmh"] if latest_p and latest_p["velocity_kmh"] is not None else None,
                    "velocity_mps": latest_p["velocity_mps"] if latest_p and latest_p["velocity_mps"] is not None else None,
                    "accel_mps2": latest_p["accel_mps2"] if latest_p and latest_p["accel_mps2"] is not None else None,
                    "world_x": latest_p["world_x"] if latest_p and latest_p["world_x"] is not None else None,
                    "world_y": latest_p["world_y"] if latest_p and latest_p["world_y"] is not None else None,
                    "quality_flag": latest_p["quality_flag"] if latest_p else "VALID_HIGH_CONFIDENCE",
                    "heading": latest_p["heading"] if latest_p else 0.0,
                    "centroid": centroid,
                    "bbox": [latest_p["x1"], latest_p["y1"], latest_p["x2"], latest_p["y2"]] if latest_p else [0, 0, 0, 0],
                    "trail": trail,
                    "duration": round(t["last_seen"] - t["first_seen"], 1),
                    "total_frames": t["total_frames"],
                    "total_distance_px": t["total_distance_px"],
                    "total_distance_m": t.get("total_distance_m", 0.0),
                })
        return result

    def get_track(self, track_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single track record with latest kinematic metrics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM heimdall_tracks WHERE track_id = ?", (track_id,))
            row = cursor.fetchone()
            if not row:
                return None
            t = dict(row)

            cursor.execute("""
                SELECT frame_index, timestamp, cx, cy, x1, y1, x2, y2, speed, heading,
                       world_x, world_y, velocity_mps, velocity_kmh, accel_mps2, quality_flag, fine_grained_class
                FROM heimdall_trajectory_points
                WHERE track_id = ?
                ORDER BY frame_index ASC
            """, (track_id,))
            pts = cursor.fetchall()
            latest_p = pts[-1] if pts else None

            # Real velocity in km/h & m/s
            vel_kmh = latest_p["velocity_kmh"] if latest_p and latest_p["velocity_kmh"] is not None else round(t["average_speed"] * 0.234, 1)
            vel_mps = latest_p["velocity_mps"] if latest_p and latest_p["velocity_mps"] is not None else round(vel_kmh / 3.6, 2)
            accel_mps2 = latest_p["accel_mps2"] if latest_p and latest_p["accel_mps2"] is not None else 0.0

            return {
                "track_id": t["track_id"],
                "normalized_class": t["normalized_class"],
                "raw_class": t["raw_class"],
                "fine_grained_class": t.get("fine_grained_class") or (latest_p["fine_grained_class"] if latest_p else t["normalized_class"]),
                "confidence": t["confidence"],
                "first_seen": t["first_seen"],
                "last_seen": t["last_seen"],
                "total_frames": t["total_frames"],
                "total_distance_px": t["total_distance_px"],
                "total_distance_meters": t.get("total_distance_m", 0.0) or round(t["total_distance_px"] * 0.065, 2),
                "average_speed": t["average_speed"],
                "current_velocity_kmh": vel_kmh,
                "current_velocity_mps": vel_mps,
                "current_acceleration_mps2": accel_mps2,
                "current_world_pos": [latest_p["world_x"], latest_p["world_y"]] if latest_p and latest_p["world_x"] is not None else None,
                "quality_flag": latest_p["quality_flag"] if latest_p else "VALID_HIGH_CONFIDENCE",
                "heading": latest_p["heading"] if latest_p else 0.0,
            }

    def get_trajectory_points(self, track_id: int) -> List[Dict[str, Any]]:
        """Retrieves all points for a single track."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT frame_index, timestamp, cx, cy, x1, y1, x2, y2, speed, heading,
                       world_x, world_y, velocity_mps, velocity_kmh, accel_mps2, quality_flag, fine_grained_class
                FROM heimdall_trajectory_points
                WHERE track_id = ?
                ORDER BY frame_index ASC
            """, (track_id,))
            rows = cursor.fetchall()
            return [
                {
                    "frame_index": r["frame_index"],
                    "timestamp": round(r["timestamp"], 3),
                    "centroid": [r["cx"], r["cy"]],
                    "bbox": [r["x1"], r["y1"], r["x2"], r["y2"]],
                    "speed": r["speed"],
                    "velocity_kmh": r["velocity_kmh"],
                    "velocity_mps": r["velocity_mps"],
                    "acceleration_mps2": r["accel_mps2"],
                    "world_pos": [r["world_x"], r["world_y"]] if r["world_x"] is not None else None,
                    "heading": r["heading"],
                    "quality_flag": r["quality_flag"],
                    "fine_grained_class": r["fine_grained_class"],
                }
                for r in rows
            ]

    # ── Metric Exporters (CSV & JSON) ─────────────────────────────────────────

    def export_metric_csv_string(self, tracks: Optional[List[TrackTrajectory]] = None) -> str:
        """Generates Level 2 Metric CSV string directly from memory or SQLite."""
        output = io.StringIO()
        fieldnames = [
            "track_id", "class", "fine_grained_class", "timestamp", "frame_index",
            "world_x", "world_y", "velocity_mps", "velocity_kmh", "acceleration_mps2",
            "heading", "distance_travelled_meters", "confidence", "quality_flag"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        if tracks:
            for track in tracks:
                dist_cum = 0.0
                for pt in track.history:
                    dist_cum += pt.distance_increment_m
                    writer.writerow({
                        "track_id": track.track_id,
                        "class": track.normalized_class.value,
                        "fine_grained_class": pt.fine_grained_class or track.fine_grained_class,
                        "timestamp": round(pt.timestamp, 3),
                        "frame_index": pt.frame_index,
                        "world_x": round(pt.ground_point[0], 2) if pt.ground_point else "",
                        "world_y": round(pt.ground_point[1], 2) if pt.ground_point else "",
                        "velocity_mps": round(pt.velocity_mps, 2) if pt.velocity_mps is not None else "",
                        "velocity_kmh": round(pt.velocity_kmh, 1) if pt.velocity_kmh is not None else "",
                        "acceleration_mps2": round(pt.acceleration_mps2, 2) if pt.acceleration_mps2 is not None else "",
                        "heading": round(pt.heading, 1),
                        "distance_travelled_meters": round(dist_cum, 2),
                        "confidence": round(pt.confidence, 3),
                        "quality_flag": pt.quality_flag,
                    })
        else:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT p.track_id, t.normalized_class, p.fine_grained_class, p.timestamp, p.frame_index,
                           p.world_x, p.world_y, p.velocity_mps, p.velocity_kmh, p.accel_mps2, p.heading,
                           p.confidence, p.quality_flag
                    FROM heimdall_trajectory_points p
                    JOIN heimdall_tracks t ON p.track_id = t.track_id
                    ORDER BY p.track_id ASC, p.frame_index ASC
                """)
                rows = cursor.fetchall()
                for r in rows:
                    writer.writerow({
                        "track_id": r["track_id"],
                        "class": r["normalized_class"],
                        "fine_grained_class": r["fine_grained_class"] or r["normalized_class"],
                        "timestamp": round(r["timestamp"], 3),
                        "frame_index": r["frame_index"],
                        "world_x": round(r["world_x"], 2) if r["world_x"] is not None else "",
                        "world_y": round(r["world_y"], 2) if r["world_y"] is not None else "",
                        "velocity_mps": round(r["velocity_mps"], 2) if r["velocity_mps"] is not None else "",
                        "velocity_kmh": round(r["velocity_kmh"], 1) if r["velocity_kmh"] is not None else "",
                        "acceleration_mps2": round(r["accel_mps2"], 2) if r["accel_mps2"] is not None else "",
                        "heading": round(r["heading"], 1),
                        "distance_travelled_meters": "",
                        "confidence": round(r["confidence"], 3),
                        "quality_flag": r["quality_flag"] or "VALID_HIGH_CONFIDENCE",
                    })

        return output.getvalue()

    def export_metric_json_data(self, tracks: Optional[List[TrackTrajectory]] = None) -> List[Dict[str, Any]]:
        """Generates Level 2 Metric JSON structure directly from memory or SQLite."""
        if tracks:
            result = []
            for track in tracks:
                t_dict = track.to_dict()
                t_dict["observations"] = [
                    {
                        "frame_index": pt.frame_index,
                        "timestamp": round(pt.timestamp, 3),
                        "bbox": [round(v, 1) for v in pt.bbox],
                        "centroid": [round(v, 1) for v in pt.centroid],
                        "world_pos": [round(v, 2) for v in pt.ground_point] if pt.ground_point else None,
                        "velocity_mps": round(pt.velocity_mps, 2) if pt.velocity_mps is not None else None,
                        "velocity_kmh": round(pt.velocity_kmh, 1) if pt.velocity_kmh is not None else None,
                        "acceleration_mps2": round(pt.acceleration_mps2, 2) if pt.acceleration_mps2 is not None else None,
                        "heading": round(pt.heading, 1),
                        "quality_flag": pt.quality_flag,
                    }
                    for pt in track.history
                ]
                result.append(t_dict)
            return result
        else:
            return self.get_all_trajectories_with_trails()

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
                        "fine_grained_class": pt.fine_grained_class or track.fine_grained_class,
                        "confidence": round(pt.confidence, 3),
                        "bbox": [round(v, 1) for v in pt.bbox],
                        "centroid": [round(v, 1) for v in pt.centroid],
                        "world_pos": [round(v, 2) for v in pt.ground_point] if pt.ground_point else None,
                        "velocity_mps": round(pt.velocity_mps, 2) if pt.velocity_mps is not None else None,
                        "velocity_kmh": round(pt.velocity_kmh, 1) if pt.velocity_kmh is not None else None,
                        "acceleration_mps2": round(pt.acceleration_mps2, 2) if pt.acceleration_mps2 is not None else None,
                        "speed": round(pt.speed_estimate, 2),
                        "heading": round(pt.heading, 1),
                        "quality_flag": pt.quality_flag,
                        "first_seen": round(track.first_seen, 3),
                        "last_seen": round(track.last_seen, 3),
                    }
                    f.write(json.dumps(line) + "\n")

    def export_csv(self, tracks: List[TrackTrajectory], filepath: str) -> None:
        """Exports per-frame observations to CSV."""
        csv_str = self.export_metric_csv_string(tracks)
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(csv_str)

    def export_trajectories_json(self, tracks: List[TrackTrajectory], filepath: str) -> None:
        """Exports session trajectories to structured JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        data = self.export_metric_json_data(tracks)
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
        """Generates and exports mission summary JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        class_breakdown = {}
        for t in tracks:
            cls_name = t.normalized_class.value
            class_breakdown[cls_name] = class_breakdown.get(cls_name, 0) + 1

        summary = {
            "video_id": video_id,
            "duration_seconds": round(duration, 2),
            "total_frames_processed": total_frames,
            "total_unique_tracks": len(tracks),
            "class_counts": class_breakdown,
            "class_breakdown": class_breakdown,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return summary

    def clear_all(self) -> None:
        """Flushes all stored tracks and trajectory points."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM heimdall_trajectory_points")
            cursor.execute("DELETE FROM heimdall_tracks")
            cursor.execute("DELETE FROM heimdall_sessions")
            conn.commit()
