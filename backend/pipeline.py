"""
Heimdallv2 End-to-End Computer Vision & Tracking Pipeline
Orchestrates: Ingestion -> Perception (BoT-SORT / ByteTrack) -> Trajectory Engine -> Telemetry Fusion -> Output Exporters
"""

import os
import time
import math
import cv2
import numpy as np
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field

from .ingestion.base import VideoSource, FrameData
from .ingestion.file_source import FileSource
from .perception.tracking.base import BaseTracker, TrackingResult
from .perception.tracking.botsort_tracker import BoTSORTTracker
from .perception.tracking.bytetrack_tracker import ByteTrackTracker
from .trajectories.engine import TrajectoryEngine
from .trajectories.storage import TrajectoryStorage
from .trajectories.models import TrackTrajectory
from .telemetry.base import TelemetryProvider, DroneTelemetry
from .telemetry.mock import MockTelemetryProvider
from .telemetry.flytbase_telemetry import FlytBaseTelemetryProvider
from .telemetry.embedded import EmbeddedTelemetryProvider
from .analytics.engine import TrafficAnalyticsEngine


@dataclass
class PipelineStatus:
    video_id: str
    status: str = "QUEUED"  # "QUEUED", "PROCESSING", "COMPLETED", "FAILED"
    progress_percent: float = 0.0
    current_frame: int = 0
    total_frames: int = 0
    fps_processing: float = 0.0
    active_tracks: int = 0
    total_unique_tracks: int = 0
    error_message: Optional[str] = None
    output_files: Dict[str, str] = field(default_factory=dict)
    summary: Optional[Dict[str, Any]] = None


class HeimdallPipeline:
    """
    Core Pipeline Orchestrator.
    Processes video streams or files and produces persistent tracks, trajectory files, and annotated video.
    """

    def __init__(
        self,
        tracker: Optional[BaseTracker] = None,
        tracker_type: str = "botsort",
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.50,
        img_size: int = 640,
        device: str = "auto",
        telemetry_provider: Optional[TelemetryProvider] = None,
        storage: Optional[TrajectoryStorage] = None,
        output_dir: str = "outputs",
        process_every_n_frames: int = 1,
        save_annotated_video: bool = True,
    ):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self.process_every_n_frames = max(1, process_every_n_frames)
        self.save_annotated_video = save_annotated_video

        # Initialize Tracker
        if tracker:
            self.tracker = tracker
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
        status.progress_percent = 0.0

        video_source.open()
        total_frames = video_source.total_frames
        if max_frames and max_frames > 0:
            total_frames = min(total_frames, max_frames) if total_frames > 0 else max_frames
        status.total_frames = total_frames
        fps = video_source.fps or 30.0
        width, height = video_source.resolution

        # Output video writer (Uses browser-compatible H.264 encoding)
        video_writer = None
        annotated_video_path = os.path.join(self.output_dir, f"{video_id}_annotated.mp4")
        if self.save_annotated_video and width > 0 and height > 0:
            # 1. Try Windows Media Foundation hardware H.264 (Native web browser compatibility)
            try:
                video_writer = cv2.VideoWriter(annotated_video_path, cv2.CAP_MSMF, cv2.VideoWriter_fourcc(*"H264"), fps, (width, height))
            except Exception:
                video_writer = None

            # 2. Fallback to FFMPEG avc1
            if video_writer is None or not video_writer.isOpened():
                try:
                    video_writer = cv2.VideoWriter(annotated_video_path, cv2.VideoWriter_fourcc(*"avc1"), fps, (width, height))
                except Exception:
                    video_writer = None

            # 3. Fallback to standard mp4v
            if video_writer is None or not video_writer.isOpened():
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

                # 2. Trajectory Update
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

                # 4. Render Annotations onto Frame
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
            )

            status.status = "COMPLETED"
            status.progress_percent = 100.0
            status.summary = summary_data
            status.output_files = {
                "annotated_video": annotated_video_path,
                "tracks_jsonl": jsonl_path,
                "tracks_csv": csv_path,
                "trajectories_json": traj_path,
                "summary_json": summary_path,
                "database": self.storage.db_path,
            }

        except Exception as e:
            status.status = "FAILED"
            status.error_message = str(e)
            if video_writer is not None:
                video_writer.release()
            video_source.close()

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
        - Solid badge with Track ID & Class
        - Historical trajectory motion trails
        - Top drone OSD status banner
        """
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        # 1. Draw Trajectory Trails
        for track in trajectories:
            if not track.history or len(track.history) < 2:
                continue

            color = track.normalized_class
            bgr = (56, 189, 248)  # default sky blue
            from .perception.classification.taxonomy import CLASS_PALETTE
            if track.normalized_class in CLASS_PALETTE:
                bgr = CLASS_PALETTE[track.normalized_class][1]

            pts = [np.array(p.centroid, dtype=np.int32) for p in track.history]
            for i in range(1, len(pts)):
                # Fade alpha from past to present
                thickness = max(1, int(2.5 * (i / len(pts))))
                cv2.line(annotated, tuple(pts[i - 1]), tuple(pts[i]), bgr, thickness)

        # 2. Draw Active Bounding Boxes & Tags
        for track in trajectories:
            if not track.is_active:
                continue

            x1, y1, x2, y2 = [int(v) for v in track.current_bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            from .perception.classification.taxonomy import CLASS_PALETTE
            bgr = CLASS_PALETTE.get(track.normalized_class, ("#E2E8F0", (240, 232, 226)))[1]

            # Bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), bgr, 2)

            # Corner accents
            corner_len = min(12, int((x2 - x1) * 0.25))
            cv2.line(annotated, (x1, y1), (x1 + corner_len, y1), (255, 255, 255), 2)
            cv2.line(annotated, (x1, y1), (x1, y1 + corner_len), (255, 255, 255), 2)
            cv2.line(annotated, (x2, y2), (x2 - corner_len, y2), (255, 255, 255), 2)
            cv2.line(annotated, (x2, y2), (x2, y2 - corner_len), (255, 255, 255), 2)

            # Label badge
            label = f"#{track.track_id} {track.normalized_class.value} {int(track.confidence * 100)}%"
            if track.is_uncertain:
                label += " [?]"

            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(annotated, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, y1), bgr, -1)
            cv2.putText(
                annotated,
                label,
                (x1 + 4, max(th + 4, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

        # 3. Top Aviation Telemetry OSD Banner
        cv2.rectangle(annotated, (0, 0), (w, 36), (15, 23, 42), -1)
        cv2.line(annotated, (0, 36), (w, 36), (56, 189, 248), 1)

        osd_text = (
            f"HEIMDALL-AI | GPS: {telemetry.latitude:.5f}, {telemetry.longitude:.5f} | "
            f"ALT: {telemetry.altitude_agl:.1f}m | HDG: {telemetry.heading_deg:.0f}deg | "
            f"BAT: {telemetry.battery_percentage:.0f}% | ACTIVE TRACKS: {len(trajectories)} | "
            f"FPS: {fps_val:.1f}"
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
        """Constructs WebSocket JSON frame."""
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
                    "raw_class": t.raw_class,
                    "confidence": round(t.confidence, 2),
                    "is_uncertain": t.is_uncertain,
                    "bbox": [round(v, 1) for v in t.current_bbox],
                    "centroid": [round(v, 1) for v in t.current_centroid],
                    "speed": round(t.current_speed, 2),
                    "heading": round(t.current_heading, 1),
                    "duration": round(t.duration_seconds, 1),
                    "trail": [
                        [round(p.centroid[0], 1), round(p.centroid[1], 1)]
                        for p in t.history[-25:]
                    ],
                }
                for t in trajectories
                if t.is_active
            ],
            "total_unique": len(self.trajectory_engine.tracks),
        }
