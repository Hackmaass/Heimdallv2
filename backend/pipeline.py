"""
Heimdallv2 Unified Perception, Tracking & Telemetry Pipeline
End-to-End processing pipeline integrating:
- Video Ingestion (File/RTSP/Webcam)
- High-Resolution SAHI & VisDrone Detection
- BoT-SORT / ByteTrack Tracking with GMC & Appearance Matching
- Level 2 Fine-Grained Classification & Metric Kinematics (Homography)
- OSD Annotation Renderer (with Metric Velocity and Fine-Grained Tags)
- WebSocket Live Broadcasting
"""

import cv2
import numpy as np
import time
import os
import math
from typing import Optional, Dict, Any, Callable, List

from .ingestion.base import VideoSource, FrameData
from .perception.tracking.base import BaseTracker, TrackingResult
from .perception.tracking.sahi_botsort_tracker import SAHIBoTSORTTracker
from .perception.tracking.botsort_tracker import BoTSORTTracker
from .perception.tracking.bytetrack_tracker import ByteTrackTracker
from .perception.classification.taxonomy import CLASS_PALETTE, RoadUserClass
from .perception.classification.fine_grained import FINE_PALETTE, FineGrainedClass
from .trajectories.engine import TrajectoryEngine
from .trajectories.homography import RoadPlaneHomography
from .trajectories.models import TrackTrajectory
from .trajectories.storage import TrajectoryStorage
from .telemetry.base import TelemetryProvider, DroneTelemetry
from .telemetry.mock import MockTelemetryProvider
from .analytics.engine import TrafficAnalyticsEngine


class PipelineStatus:
    def __init__(self, video_id: str):
        self.video_id = video_id
        self.status = "IDLE"  # IDLE, PROCESSING, COMPLETED, ERROR
        self.current_frame = 0
        self.total_frames = 0
        self.progress_percent = 0.0
        self.fps_processing = 0.0
        self.active_tracks = 0
        self.total_unique_tracks = 0
        self.error_message: Optional[str] = None


class HeimdallPipeline:
    """
    Core pipeline orchestrator for Heimdallv2.
    """

    def __init__(
        self,
        tracker: Optional[BaseTracker] = None,
        tracker_type: str = "botsort",
        model_path: str = "yolov8s-visdrone.pt",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        img_size: int = 1280,
        device: str = "auto",
        telemetry_provider: Optional[TelemetryProvider] = None,
        storage: Optional[TrajectoryStorage] = None,
        output_dir: str = "outputs",
        process_every_n_frames: int = 1,
        save_annotated_video: bool = True,
        enable_sahi: bool = False,
        sahi_slice_size: int = 960,
    ):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self.process_every_n_frames = max(1, process_every_n_frames)
        self.save_annotated_video = save_annotated_video

        # Initialize Tracker
        if tracker:
            self.tracker = tracker
        elif enable_sahi:
            self.tracker = SAHIBoTSORTTracker(
                model_name_or_path=model_path,
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                img_size=img_size,
                device=device,
                slice_size=sahi_slice_size,
            )
        elif tracker_type == "bytetrack":
            self.tracker = ByteTrackTracker(
                model_name_or_path=model_path,
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                img_size=img_size,
                device=device,
            )
        else:
            self.tracker = BoTSORTTracker(
                model_name_or_path=model_path,
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                img_size=img_size,
                device=device,
            )

        self.storage = storage or TrajectoryStorage(db_path=os.path.join(output_dir, "heimdall.db"))
        self.trajectory_engine = TrajectoryEngine(storage=self.storage)

        # Auto-load homography calibration if present
        homography = RoadPlaneHomography.load("configs/calibration.json")
        if homography.is_calibrated:
            self.trajectory_engine.set_calibration(homography)

        self.telemetry_provider = telemetry_provider or MockTelemetryProvider()
        self.analytics_engine = TrafficAnalyticsEngine()

    def process_video(
        self,
        video_source: VideoSource,
        video_id: str = "job_01",
        on_frame_callback: Optional[Callable[[Dict[str, Any], np.ndarray], None]] = None,
        status_container: Optional[PipelineStatus] = None,
        max_frames: Optional[int] = None,
    ) -> PipelineStatus:
        """
        Executes end-to-end processing loop on video source.
        """
        status = status_container or PipelineStatus(video_id=video_id)
        status.status = "PROCESSING"

        total_frames = video_source.total_frames
        status.total_frames = min(total_frames, max_frames) if max_frames else total_frames

        fps = video_source.fps or 30.0
        width = video_source.width or 1920
        height = video_source.height or 1080

        # Auto-calibrate ground homography from flight telemetry if not manually calibrated
        if not self.trajectory_engine.speed_estimator.is_calibrated and hasattr(self.telemetry_provider, "get_ground_homography"):
            try:
                telemetry_h = self.telemetry_provider.get_ground_homography(
                    image_width=width,
                    image_height=height,
                    frame_index=0,
                    timestamp=0.0,
                )
                if telemetry_h and telemetry_h.is_calibrated:
                    self.trajectory_engine.set_calibration(telemetry_h)
            except Exception:
                pass

        # Create video writer if enabled
        video_writer = None
        annotated_video_path = os.path.join(self.output_dir, f"{video_id}_annotated.mp4")
        if self.save_annotated_video:
            try:
                fourcc = cv2.VideoWriter_fourcc(*"avc1")
                video_writer = cv2.VideoWriter(annotated_video_path, fourcc, fps, (width, height))
                if not video_writer.isOpened():
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    video_writer = cv2.VideoWriter(annotated_video_path, fourcc, fps, (width, height))
            except Exception:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                video_writer = cv2.VideoWriter(annotated_video_path, fourcc, fps, (width, height))

        t_start = time.perf_counter()
        frame_counter = 0

        try:
            for frame_data in video_source.frames():
                frame = frame_data.frame
                frame_idx = frame_data.frame_index
                timestamp = frame_data.timestamp_seconds

                if max_frames and frame_counter >= max_frames:
                    break

                # Frame skipping support
                if frame_idx % self.process_every_n_frames != 0:
                    if video_writer is not None:
                        video_writer.write(frame)
                    continue

                # 1. Tracker Update
                tracking_result: TrackingResult = self.tracker.update(
                    frame=frame,
                    frame_index=frame_idx,
                    timestamp=timestamp,
                )

                # 2. Trajectory & Kinematics Update
                active_trajectories = self.trajectory_engine.update_tracks(
                    active_objects=tracking_result.tracks,
                    frame_index=frame_idx,
                    timestamp=timestamp,
                )

                # 3. Telemetry Ingestion
                telemetry: DroneTelemetry = self.telemetry_provider.get_telemetry(
                    frame=frame,
                    frame_index=frame_idx,
                    timestamp=timestamp,
                )

                # 4. Render Tactical Annotations onto Frame
                annotated_frame = self._render_annotations(
                    frame=frame,
                    trajectories=active_trajectories,
                    telemetry=telemetry,
                    frame_idx=frame_idx,
                    fps_val=(frame_counter / max(0.001, time.perf_counter() - t_start)),
                )

                if video_writer is not None:
                    video_writer.write(annotated_frame)

                # 5. Broadcast to WebSocket callback if attached
                if on_frame_callback is not None:
                    payload = self._build_frame_payload(
                        frame_idx=frame_idx,
                        timestamp=timestamp,
                        trajectories=active_trajectories,
                        telemetry=telemetry,
                    )
                    on_frame_callback(payload, annotated_frame)

                frame_counter += 1
                status.current_frame = frame_idx
                if total_frames > 0:
                    status.progress_percent = min(99.0, round((frame_idx / total_frames) * 100.0, 1))
                status.active_tracks = len(tracking_result.tracks)
                status.total_unique_tracks = len(self.trajectory_engine.tracks)
                status.fps_processing = round(frame_counter / max(0.001, time.perf_counter() - t_start), 1)

            # Finalize Output Exporters
            if video_writer is not None:
                video_writer.release()

            video_source.close()

            all_tracks = self.trajectory_engine.get_all_trajectories()

            # Save SQLite Database
            self.trajectory_engine.persist_all(session_id=video_id)

            # Export Files
            jsonl_path = os.path.join(self.output_dir, f"{video_id}_tracks.jsonl")
            csv_path = os.path.join(self.output_dir, f"{video_id}_tracks.csv")
            traj_path = os.path.join(self.output_dir, f"{video_id}_trajectories.json")
            summary_path = os.path.join(self.output_dir, f"{video_id}_summary.json")

            self.storage.export_jsonl(all_tracks, jsonl_path)
            self.storage.export_csv(all_tracks, csv_path)
            self.storage.export_trajectories_json(all_tracks, traj_path)

            total_duration = total_frames / max(1.0, fps)
            summary_data = self.storage.export_summary_json(
                video_id=video_id,
                duration=total_duration,
                total_frames=frame_counter,
                tracks=all_tracks,
                filepath=summary_path,
            ) if hasattr(self.storage, 'export_summary_json') else {}

            status.status = "COMPLETED"
            status.progress_percent = 100.0

        except Exception as e:
            status.status = "ERROR"
            status.error_message = str(e)
            if video_writer is not None:
                video_writer.release()
            video_source.close()
            raise e

        return status

    def _render_annotations(
        self,
        frame: np.ndarray,
        trajectories: List[TrackTrajectory],
        telemetry: DroneTelemetry,
        frame_idx: int,
        fps_val: float,
    ) -> np.ndarray:
        """
        Draws high-density tactical command annotations:
        - Polished bounding box with corner brackets
        - Level 2 Multi-line Badge: #ID Fine-Class & Speed (km/h)
        - Historical trajectory motion trails (with gap rejection)
        - Top drone OSD status banner
        """
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        # 1. Draw Trajectory Trails (Anti-Aliased Smooth Motion Trails)
        for track in trajectories:
            if not track.history or len(track.history) < 2 or track.total_frames < 2:
                continue

            bgr = (56, 189, 248)  # default sky blue
            if track.normalized_class in CLASS_PALETTE:
                bgr = CLASS_PALETTE[track.normalized_class][1]

            pts = [np.array(p.centroid, dtype=np.int32) for p in track.history]
            for i in range(1, len(pts)):
                p1, p2 = pts[i - 1], pts[i]
                # If distance between consecutive points > 60px, do not draw across the gap
                if np.hypot(p2[0] - p1[0], p2[1] - p1[1]) > 60.0:
                    continue
                thickness = max(1, min(3, int(2.5 * (i / len(pts)))))
                cv2.line(annotated, tuple(p1), tuple(p2), bgr, thickness, cv2.LINE_AA)

        # 2. Draw Active Bounding Boxes & Tags (Confirmed Tracks Only)
        for track in trajectories:
            if not track.is_active or track.total_frames < 2:
                continue

            x1, y1, x2, y2 = [int(v) for v in track.current_bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            bgr = CLASS_PALETTE.get(track.normalized_class, ("#E2E8F0", (240, 232, 226)))[1]

            # Bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), bgr, 2)

            # Corner accents
            corner_len = min(12, int((x2 - x1) * 0.25))
            cv2.line(annotated, (x1, y1), (x1 + corner_len, y1), (255, 255, 255), 2)
            cv2.line(annotated, (x1, y1), (x1, y1 + corner_len), (255, 255, 255), 2)
            cv2.line(annotated, (x2, y2), (x2 - corner_len, y2), (255, 255, 255), 2)
            cv2.line(annotated, (x2, y2), (x2, y2 - corner_len), (255, 255, 255), 2)

            # Level 2 Label badge: #ID Fine-Class & Speed
            speed_str = f"{track.current_speed:.1f} {track.speed_unit}"
            label_top = f"#{track.track_id} {track.fine_grained_class}"
            label_bot = f"{speed_str}"

            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw1, th1), _ = cv2.getTextSize(label_top, font, 0.45, 1)
            (tw2, th2), _ = cv2.getTextSize(label_bot, font, 0.40, 1)
            badge_w = max(tw1, tw2) + 8
            badge_h = th1 + th2 + 12

            cv2.rectangle(annotated, (x1, max(0, y1 - badge_h)), (x1 + badge_w, y1), bgr, -1)
            cv2.putText(
                annotated,
                label_top,
                (x1 + 4, max(th1 + 2, y1 - th2 - 6)),
                font,
                0.45,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                annotated,
                label_bot,
                (x1 + 4, max(badge_h - 2, y1 - 2)),
                font,
                0.40,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

        # 3. Top Aviation Telemetry OSD Banner
        cv2.rectangle(annotated, (0, 0), (w, 36), (15, 23, 42), -1)
        cv2.line(annotated, (0, 36), (w, 36), (56, 189, 248), 1)

        calib_str = "METRIC [CALIBRATED]" if any(t.is_calibrated for t in trajectories) else "RELATIVE [px/s]"
        osd_text = (
            f"HEIMDALL-AI | GPS: {telemetry.latitude:.5f}, {telemetry.longitude:.5f} | "
            f"ALT: {telemetry.altitude_agl:.1f}m | HDG: {telemetry.heading_deg:.0f}deg | "
            f"ACTIVE: {len(trajectories)} | {calib_str} | FPS: {fps_val:.1f}"
        )
        cv2.putText(
            annotated,
            osd_text,
            (16, 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (226, 232, 240),
            1,
            cv2.LINE_AA,
        )

        return annotated

    def _build_frame_payload(
        self,
        frame_idx: int,
        timestamp: float,
        trajectories: List[TrackTrajectory],
        telemetry: DroneTelemetry,
    ) -> Dict[str, Any]:
        """Constructs WebSocket JSON frame with Level 2 metric data."""
        return {
            "frame": frame_idx,
            "timestamp": round(timestamp, 3),
            "telemetry": {
                "lat": telemetry.latitude,
                "lng": telemetry.longitude,
                "alt": telemetry.altitude_agl,
                "heading": telemetry.heading_deg,
                "battery": telemetry.battery_percentage,
                "speed": telemetry.ground_speed_mps,
                "mode": telemetry.flight_mode,
            },
            "tracks": [
                {
                    "id": t.track_id,
                    "class": t.normalized_class.value,
                    "fine_grained_class": t.fine_grained_class,
                    "fine_grained_conf": round(t.fine_grained_confidence, 2),
                    "raw_class": t.raw_class,
                    "confidence": round(t.confidence, 2),
                    "is_uncertain": t.is_uncertain,
                    "is_calibrated": t.is_calibrated,
                    "speed_unit": t.speed_unit,
                    "quality_flag": t.quality_flag,
                    "bbox": [round(v, 1) for v in t.current_bbox],
                    "centroid": [round(v, 1) for v in t.current_centroid],
                    "world_pos": [round(v, 2) for v in t.current_world_pos] if t.current_world_pos else None,
                    "speed": round(t.current_speed, 1),
                    "velocity_mps": round(t.current_velocity_mps, 2) if t.current_velocity_mps is not None else None,
                    "velocity_kmh": round(t.current_velocity_kmh, 1) if t.current_velocity_kmh is not None else None,
                    "acceleration_mps2": round(t.current_acceleration_mps2, 2) if t.current_acceleration_mps2 is not None else None,
                    "heading": round(t.current_heading, 1),
                    "distance_travelled_m": round(t.total_distance_meters, 2),
                    "duration": round(t.duration_seconds, 1),
                    "trail": [
                        [round(p.centroid[0], 1), round(p.centroid[1], 1)]
                        for p in t.history[-100:]
                    ],
                }
                for t in trajectories
                if t.is_active and t.total_frames >= 2
            ],
            "total_unique": len([t for t in self.trajectory_engine.tracks.values() if t.total_frames >= 2]),
        }
