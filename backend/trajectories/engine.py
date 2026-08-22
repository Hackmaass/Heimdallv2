"""
Trajectory Engine Module
Manages live spatial-temporal trajectories, historical trails, speed smoothing,
gap interpolation, outlier jump rejection, and persistence.
"""

import math
from typing import Dict, List, Optional, Tuple
from .models import TrackTrajectory, TrajectoryPoint
from .speed_estimator import BaseSpeedEstimator, PixelSpeedEstimator, SpeedEstimate
from .storage import TrajectoryStorage
from ..perception.tracking.base import TrackedObject


class TrajectoryEngine:
    """
    Stateful trajectory engine managing moving trails, persistent object histories,
    kinematic smoothing, outlier suppression, and gap interpolation.
    """

    def __init__(
        self,
        max_history_points: int = 120,
        speed_estimator: Optional[BaseSpeedEstimator] = None,
        storage: Optional[TrajectoryStorage] = None,
        speed_smoothing_window: int = 5,
        ema_alpha: float = 0.70,          # Weight for new measurement (0.70 = 30% smoothing)
        max_jump_px: float = 120.0,       # Maximum allowed displacement per frame before clamping
        min_confirmed_hits: int = 1,      # Minimum consecutive detections before confirmation
    ):
        self.max_history_points = max_history_points
        self.speed_estimator = speed_estimator or PixelSpeedEstimator()
        self.storage = storage or TrajectoryStorage()
        self.speed_smoothing_window = speed_smoothing_window
        self.ema_alpha = ema_alpha
        self.max_jump_px = max_jump_px
        self.min_confirmed_hits = min_confirmed_hits

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
        Applies EMA centroid smoothing, outlier gating, and occlusion gap interpolation.
        """
        current_frame_ids = set()

        for obj in active_objects:
            tid = obj.track_id
            current_frame_ids.add(tid)

            raw_cx, raw_cy = obj.centroid
            smoothed_cx, smoothed_cy = raw_cx, raw_cy

            if tid not in self.tracks:
                # Initialize new candidate trajectory
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
                    current_centroid=(smoothed_cx, smoothed_cy),
                    current_speed=obj.speed_estimate,
                    current_heading=obj.heading,
                    history=[],
                )
                self.tracks[tid] = traj
            else:
                traj = self.tracks[tid]
                last_pt = traj.history[-1] if traj.history else None

                # ── Step 1: Outlier Jump Suppression & EMA Centroid Smoothing ──
                if last_pt is not None:
                    dx = raw_cx - last_pt.centroid[0]
                    dy = raw_cy - last_pt.centroid[1]
                    dist = math.hypot(dx, dy)
                    frames_elapsed = max(1, frame_index - last_pt.frame_index)

                    # If an association jumps unrealistically far, clamp the leap
                    max_allowed_dist = self.max_jump_px * frames_elapsed
                    if dist > max_allowed_dist and dist > 0.001:
                        scale = max_allowed_dist / dist
                        raw_cx = last_pt.centroid[0] + dx * scale
                        raw_cy = last_pt.centroid[1] + dy * scale

                    # ── Step 2: Gap Interpolation for Missed/Occluded Frames ───
                    if frames_elapsed > 1 and frames_elapsed <= 6:
                        # Linear interpolation across intermediate frames
                        for f_step in range(1, frames_elapsed):
                            frac = f_step / float(frames_elapsed)
                            interp_t = last_pt.timestamp + frac * (timestamp - last_pt.timestamp)
                            interp_cx = last_pt.centroid[0] + frac * (raw_cx - last_pt.centroid[0])
                            interp_cy = last_pt.centroid[1] + frac * (raw_cy - last_pt.centroid[1])
                            interp_pt = TrajectoryPoint(
                                frame_index=last_pt.frame_index + f_step,
                                timestamp=interp_t,
                                bbox=obj.bbox,
                                centroid=(interp_cx, interp_cy),
                                velocity=last_pt.velocity,
                                speed_estimate=last_pt.speed_estimate,
                                heading=last_pt.heading,
                                confidence=obj.confidence * 0.8,
                            )
                            traj.history.append(interp_pt)

                    # EMA exponential moving average for smooth, continuous line
                    smoothed_cx = self.ema_alpha * raw_cx + (1.0 - self.ema_alpha) * last_pt.centroid[0]
                    smoothed_cy = self.ema_alpha * raw_cy + (1.0 - self.ema_alpha) * last_pt.centroid[1]

                traj.last_seen = timestamp
                traj.last_frame = frame_index
                traj.total_frames += 1
                traj.is_active = True
                traj.current_bbox = obj.bbox
                traj.current_centroid = (smoothed_cx, smoothed_cy)
                traj.confidence = max(traj.confidence, obj.confidence)

            # ── Step 3: Compute Smoothed Kinematics (Speed & Heading) ───────
            speed_val = obj.speed_estimate
            heading_val = obj.heading

            if traj.history:
                last_pt = traj.history[-1]
                dt = max(0.001, timestamp - last_pt.timestamp)
                speed_est: SpeedEstimate = self.speed_estimator.estimate(
                    (smoothed_cx, smoothed_cy), last_pt.centroid, dt
                )
                speed_val = speed_est.value

                # Smooth speed with trailing window
                recent_speeds = [p.speed_estimate for p in traj.history[-self.speed_smoothing_window:]] + [speed_val]
                smoothed_speed = sum(recent_speeds) / len(recent_speeds)
                speed_val = round(smoothed_speed, 2)

                # Smooth heading
                dx = smoothed_cx - last_pt.centroid[0]
                dy = smoothed_cy - last_pt.centroid[1]
                if math.hypot(dx, dy) > 1.5:
                    rad = math.atan2(dy, dx)
                    heading_val = round((math.degrees(rad) + 360.0) % 360.0, 1)

            traj.current_speed = speed_val
            traj.current_heading = heading_val

            point = TrajectoryPoint(
                frame_index=frame_index,
                timestamp=timestamp,
                bbox=obj.bbox,
                centroid=(smoothed_cx, smoothed_cy),
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
        # Return confirmed trajectories (filters out 1-2 frame transient noise)
        return [t for t in self.tracks.values() if t.total_frames >= self.min_confirmed_hits or t.is_active]

    def get_active_trajectories(self) -> List[TrackTrajectory]:
        """Returns confirmed active trajectories."""
        return [t for t in self.tracks.values() if t.is_active and t.total_frames >= self.min_confirmed_hits]

    def get_all_trajectories(self) -> List[TrackTrajectory]:
        """Returns all confirmed trajectories across the session."""
        return [t for t in self.tracks.values() if t.total_frames >= self.min_confirmed_hits]

    def get_trajectory(self, track_id: int) -> Optional[TrackTrajectory]:
        return self.tracks.get(track_id)

    def persist_all(self, session_id: Optional[str] = None) -> None:
        """Persists all confirmed tracks and points into SQLite storage."""
        if not self.storage:
            return
        confirmed_tracks = [t for t in self.tracks.values() if t.total_frames >= self.min_confirmed_hits]
        for track in confirmed_tracks:
            self.storage.save_track(track, session_id)
            for pt in track.history:
                self.storage.save_trajectory_point(track.track_id, pt)

    def reset(self) -> None:
        self.tracks.clear()
        self.active_track_ids.clear()
