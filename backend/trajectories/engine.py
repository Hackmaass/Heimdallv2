"""
Trajectory Engine Module
Manages live spatial-temporal trajectories, historical trails, and persistence.
"""

from typing import Dict, List, Optional, Tuple
from .models import TrackTrajectory, TrajectoryPoint
from .speed_estimator import BaseSpeedEstimator, PixelSpeedEstimator, SpeedEstimate
from .storage import TrajectoryStorage
from ..perception.tracking.base import TrackedObject


class TrajectoryEngine:
    """
    Stateful trajectory engine managing moving trails, persistent object histories,
    speed smoothing, and persistence.
    """

    def __init__(
        self,
        max_history_points: int = 100,
        speed_estimator: Optional[BaseSpeedEstimator] = None,
        storage: Optional[TrajectoryStorage] = None,
        speed_smoothing_window: int = 5,
    ):
        self.max_history_points = max_history_points
        self.speed_estimator = speed_estimator or PixelSpeedEstimator()
        self.storage = storage or TrajectoryStorage()
        self.speed_smoothing_window = speed_smoothing_window

        self.tracks: Dict[int, TrackTrajectory] = {}
        self.active_track_ids: set = set()

    def update_tracks(
        self,
        active_objects: List[TrackedObject],
        frame_index: int,
        timestamp: float,
    ) -> List[TrackTrajectory]:
        """
        Updates internal trajectory database with current frame's tracking output.
        """
        current_frame_ids = set()

        for obj in active_objects:
            tid = obj.track_id
            current_frame_ids.add(tid)

            if tid not in self.tracks:
                # Initialize new trajectory
                traj = TrackTrajectory(
                    track_id=tid,
                    raw_class=obj.raw_class,
                    normalized_class=obj.normalized.normalized_class,
                    confidence=obj.confidence,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    first_frame=frame_index,
                    last_frame=frame_index,
                    total_frames=1,
                    is_active=True,
                    is_uncertain=obj.normalized.is_uncertain,
                    current_bbox=obj.bbox,
                    current_centroid=obj.centroid,
                    current_speed=obj.speed_estimate,
                    current_heading=obj.heading,
                    history=[],
                )
                self.tracks[tid] = traj
            else:
                traj = self.tracks[tid]
                traj.last_seen = timestamp
                traj.last_frame = frame_index
                traj.total_frames += 1
                traj.is_active = True
                traj.current_bbox = obj.bbox
                traj.current_centroid = obj.centroid
                traj.confidence = max(traj.confidence, obj.confidence)

            # Compute smoothed speed & heading
            speed_val = obj.speed_estimate
            heading_val = obj.heading

            if traj.history:
                last_pt = traj.history[-1]
                dt = timestamp - last_pt.timestamp
                speed_est: SpeedEstimate = self.speed_estimator.estimate(
                    obj.centroid, last_pt.centroid, dt
                )
                speed_val = speed_est.value

                # Smooth speed with trailing window
                recent_speeds = [p.speed_estimate for p in traj.history[-self.speed_smoothing_window:]] + [speed_val]
                smoothed_speed = sum(recent_speeds) / len(recent_speeds)
                speed_val = round(smoothed_speed, 2)

            traj.current_speed = speed_val
            traj.current_heading = heading_val

            point = TrajectoryPoint(
                frame_index=frame_index,
                timestamp=timestamp,
                bbox=obj.bbox,
                centroid=obj.centroid,
                velocity=obj.velocity,
                speed_estimate=speed_val,
                heading=heading_val,
                confidence=obj.confidence,
            )
            traj.history.append(point)

            # Cap history window
            if len(traj.history) > self.max_history_points:
                traj.history.pop(0)

        # Mark missing tracks as inactive
        for tid, traj in self.tracks.items():
            if tid not in current_frame_ids:
                traj.is_active = False

        self.active_track_ids = current_frame_ids
        return list(self.tracks.values())

    def get_active_trajectories(self) -> List[TrackTrajectory]:
        return [t for t in self.tracks.values() if t.is_active]

    def get_all_trajectories(self) -> List[TrackTrajectory]:
        return list(self.tracks.values())

    def get_trajectory(self, track_id: int) -> Optional[TrackTrajectory]:
        return self.tracks.get(track_id)

    def persist_all(self, session_id: Optional[str] = None) -> None:
        """Persists all current tracks and points into SQLite storage."""
        if not self.storage:
            return
        for track in self.tracks.values():
            self.storage.save_track(track, session_id)
            for pt in track.history:
                self.storage.save_trajectory_point(track.track_id, pt)

    def reset(self) -> None:
        self.tracks.clear()
        self.active_track_ids.clear()
