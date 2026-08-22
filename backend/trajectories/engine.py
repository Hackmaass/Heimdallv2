"""
Trajectory Engine Module (Level 1 Baseline + Level 2 Extended Kinematics)
Manages live spatial-temporal trajectories, historical trails, speed smoothing,
fine-grained classification caching, ground-plane kinematics, and quality control.
"""

import math
from typing import Dict, List, Optional, Tuple
from .models import TrackTrajectory, TrajectoryPoint
from .speed_estimator import BaseSpeedEstimator, PixelSpeedEstimator, GroundPlaneSpeedEstimator, KinematicState
from .homography import RoadPlaneHomography
from .quality import KinematicQualityFlag
from .storage import TrajectoryStorage
from ..perception.tracking.base import TrackedObject
from ..perception.classification.fine_grained import FineGrainedClassifier, FineGrainedClassification


class TrajectoryEngine:
    """
    Stateful trajectory engine managing moving trails, persistent object histories,
    kinematic smoothing, fine-grained classification, and metric kinematics.
    """

    def __init__(
        self,
        max_history_points: int = 150,
        speed_estimator: Optional[BaseSpeedEstimator] = None,
        storage: Optional[TrajectoryStorage] = None,
        speed_smoothing_window: int = 5,
        ema_alpha: float = 0.70,          # Weight for new measurement
        max_jump_px: float = 120.0,       # Maximum allowed displacement per frame
        min_confirmed_hits: int = 1,      # Minimum consecutive detections
    ):
        self.max_history_points = max_history_points
        self.speed_estimator = speed_estimator or PixelSpeedEstimator()
        self.classifier = FineGrainedClassifier()
        self.storage = storage or TrajectoryStorage()
        self.speed_smoothing_window = speed_smoothing_window
        self.ema_alpha = ema_alpha
        self.max_jump_px = max_jump_px
        self.min_confirmed_hits = min_confirmed_hits

        self.tracks: Dict[int, TrackTrajectory] = {}
        self.active_track_ids: set = set()

    def set_calibration(self, homography: RoadPlaneHomography) -> None:
        """Dynamically applies ground-plane homography calibration to the engine."""
        self.speed_estimator = GroundPlaneSpeedEstimator(homography)

    def update_tracks(
        self,
        active_objects: List[TrackedObject],
        frame_index: int,
        timestamp: float,
    ) -> List[TrackTrajectory]:
        """
        Updates internal trajectory database with current frame's tracking output.
        Applies EMA centroid smoothing, outlier gating, fine-grained classification, and kinematics.
        """
        current_frame_ids = set()

        for obj in active_objects:
            tid = obj.track_id
            current_frame_ids.add(tid)

            raw_cx, raw_cy = obj.centroid
            smoothed_cx, smoothed_cy = raw_cx, raw_cy

            # ── Step 1: Second-Stage Fine-Grained Classification ─────────────
            fine_result: FineGrainedClassification = self.classifier.classify_track(
                track_id=tid,
                raw_class_name=obj.raw_class,
                detection_conf=obj.confidence,
                bbox=obj.bbox,
                speed_estimate=obj.speed_estimate,
            )

            if tid not in self.tracks:
                # Initialize new candidate trajectory
                traj = TrackTrajectory(
                    track_id=tid,
                    raw_class=obj.raw_class,
                    normalized_class=obj.normalized.normalized_class,
                    fine_grained_class=fine_result.fine_class.value,
                    fine_grained_confidence=fine_result.confidence,
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
                    total_distance_meters=0.0,
                    history=[],
                )
                self.tracks[tid] = traj
            else:
                traj = self.tracks[tid]
                # Update fine-grained classification
                traj.fine_grained_class = fine_result.fine_class.value
                traj.fine_grained_confidence = fine_result.confidence

                last_pt = traj.history[-1] if traj.history else None

                # ── Step 2: Outlier Jump Gating & Track Discontinuity Check ───
                if last_pt is not None:
                    dx = raw_cx - last_pt.centroid[0]
                    dy = raw_cy - last_pt.centroid[1]
                    dist = math.hypot(dx, dy)
                    frames_elapsed = max(1, frame_index - last_pt.frame_index)
                    max_allowed_dist = min(120.0, self.max_jump_px * min(frames_elapsed, 3))

                    # If an association jumps across roads / buildings (> max_allowed_dist):
                    # It is an ID swap error from the tracker. Break the trail history
                    # so no line is drawn cutting across buildings or roadways.
                    if dist > max_allowed_dist:
                        traj.history.clear()
                        smoothed_cx = raw_cx
                        smoothed_cy = raw_cy
                    else:
                        # Gap Interpolation for Missed/Occluded Frames
                        if 1 < frames_elapsed <= 5:
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
                                    fine_grained_class=traj.fine_grained_class,
                                    fine_grained_confidence=traj.fine_grained_confidence,
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

            # ── Step 3: Metric Kinematics Computation ────────────────────────
            prev_bbox = traj.history[-1].bbox if traj.history else None
            prev_velocity_mps = traj.current_velocity_mps
            dt = max(0.001, (timestamp - traj.history[-1].timestamp)) if traj.history else 0.033

            kinematics: KinematicState = self.speed_estimator.estimate_kinematics(
                current_bbox=obj.bbox,
                prev_bbox=prev_bbox,
                dt=dt,
                prev_velocity_mps=prev_velocity_mps,
                history_length=len(traj.history) + 1,
            )

            # Update TrackTrajectory state
            traj.is_calibrated = kinematics.is_calibrated
            traj.speed_unit = kinematics.speed_unit
            traj.current_speed = kinematics.speed_value
            traj.current_velocity_mps = kinematics.velocity_mps
            traj.current_velocity_kmh = kinematics.velocity_kmh
            traj.current_acceleration_mps2 = kinematics.acceleration_mps2
            traj.current_world_pos = kinematics.world_pos
            traj.current_heading = kinematics.heading_deg if kinematics.heading_deg > 0 else traj.current_heading
            traj.quality_flag = kinematics.quality_assessment.flag.value
            traj.total_distance_meters += kinematics.distance_increment_m

            # Create TrajectoryPoint observation
            point = TrajectoryPoint(
                frame_index=frame_index,
                timestamp=timestamp,
                bbox=obj.bbox,
                centroid=(smoothed_cx, smoothed_cy),
                velocity=obj.velocity,
                speed_estimate=kinematics.speed_value,
                heading=traj.current_heading,
                confidence=obj.confidence,
                ground_point=kinematics.world_pos,
                velocity_mps=kinematics.velocity_mps,
                velocity_kmh=kinematics.velocity_kmh,
                acceleration_mps2=kinematics.acceleration_mps2,
                distance_increment_m=kinematics.distance_increment_m,
                quality_flag=kinematics.quality_assessment.flag.value,
                fine_grained_class=traj.fine_grained_class,
                fine_grained_confidence=traj.fine_grained_confidence,
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

    def clear(self) -> None:
        self.tracks.clear()
        self.active_track_ids.clear()
        self.classifier.clear()

    def reset(self) -> None:
        self.clear()
