"""
FastAPI REST Route Handlers for Heimdallv2
"""

import os
import shutil
import uuid
import asyncio
from typing import Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from .schemas import ProcessVideoRequest, JobStatusResponse, GimbalRequest, MissionRequest
from .websocket import ConnectionManager
from ..pipeline import HeimdallPipeline, PipelineStatus
from ..ingestion.file_source import FileSource
from ..trajectories.storage import TrajectoryStorage
from ..integrations.flytbase.client import FlytBaseClient
from ..integrations.flytbase.models import FlytBaseMissionPlan, FlytBaseWaypoint

router = APIRouter(prefix="/api")

# In-memory registry of active and completed video processing jobs
JOB_REGISTRY: Dict[str, PipelineStatus] = {}

# Shared Singleton services
storage = TrajectoryStorage()
flytbase_client = FlytBaseClient()
ws_manager = ConnectionManager()


def _run_pipeline_job(
    video_path: str,
    job_status: PipelineStatus,
    req: ProcessVideoRequest,
    main_loop: Optional[asyncio.AbstractEventLoop] = None,
):
    """Background worker executing video processing with duration and time-window support."""
    fps = 30.0
    start_frame = 0
    max_frames = req.max_frames

    # Probe video to calculate frame offsets if time controls are provided
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            cap.release()

            if req.start_seconds and req.start_seconds > 0:
                start_frame = int(req.start_seconds * fps)

            if req.duration_seconds and req.duration_seconds > 0:
                calc_max = int(req.duration_seconds * fps)
                max_frames = calc_max if max_frames is None else min(max_frames, calc_max)
    except Exception:
        pass

    pipeline = HeimdallPipeline(
        tracker_type=req.tracker_type or "botsort",
        model_path=req.model_name or "yolov8n.pt",
        confidence_threshold=req.confidence_threshold or 0.25,
        process_every_n_frames=req.process_every_n_frames or 1,
        save_annotated_video=req.save_annotated_video if req.save_annotated_video is not None else True,
        storage=storage,
        output_dir="outputs",
        enable_sahi=req.enable_sahi if req.enable_sahi is not None else False,
        sahi_slice_size=req.sahi_slice_size or 960,
    )

    def on_frame(payload: Dict[str, Any], frame_bgr):
        # Schedule WebSocket broadcast on the server's main event loop
        try:
            target_loop = main_loop
            if target_loop and target_loop.is_running():
                asyncio.run_coroutine_threadsafe(ws_manager.broadcast_frame(payload, frame_bgr), target_loop)
        except Exception:
            pass

    source = FileSource(file_path=video_path, start_frame=start_frame, max_frames=max_frames)
    pipeline.process_video(
        video_source=source,
        video_id=job_status.video_id,
        on_frame_callback=on_frame,
        status_container=job_status,
        max_frames=max_frames,
    )


# ── Health & Diagnostics ───────────────────────────────────────────────────────

@router.get("/health")
async def get_health():
    """System health & compute device diagnostics."""
    import torch
    cuda_avail = torch.cuda.is_available()
    device_name = torch.cuda.get_device_name(0) if cuda_avail else "CPU"

    return {
        "status": "online",
        "service": "Heimdallv2 Traffic Intelligence & Operations Platform",
        "version": "2.0.0",
        "compute": {
            "cuda_available": cuda_avail,
            "device": device_name,
        },
        "flytbase_mode": flytbase_client.mode,
        "active_ws_subscribers": len(ws_manager.active_connections),
        "total_completed_jobs": sum(1 for j in JOB_REGISTRY.values() if j.status == "COMPLETED"),
    }


# ── Video Ingestion & Processing ───────────────────────────────────────────────

@router.get("/videos")
async def list_available_videos():
    """Lists video files available in data/ directory with duration and resolution metadata."""
    videos = []
    if os.path.exists("data"):
        for f in os.listdir("data"):
            if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                p = os.path.join("data", f)
                size_mb = round(os.path.getsize(p) / (1024 * 1024), 2)
                duration_s = None
                fps = None
                res = None
                try:
                    import cv2
                    cap = cv2.VideoCapture(p)
                    if cap.isOpened():
                        fps = round(cap.get(cv2.CAP_PROP_FPS) or 30.0, 1)
                        total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
                        duration_s = round(total_f / max(1.0, fps), 1) if fps > 0 else 0.0
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        res = f"{w}x{h}"
                        cap.release()
                except Exception:
                    pass

                videos.append({
                    "filename": f,
                    "path": p.replace("\\", "/"),
                    "size_mb": size_mb,
                    "duration_seconds": duration_s,
                    "fps": fps,
                    "resolution": res,
                })
    return {"videos": videos}


@router.post("/video/upload")
async def upload_video(file: UploadFile = File(...)):
    """Uploads a drone video file to data/ directory with metadata extraction."""
    os.makedirs("data", exist_ok=True)
    video_id = f"vid_{uuid.uuid4().hex[:8]}"
    ext = os.path.splitext(file.filename)[1] or ".mp4"
    dest_filename = f"{video_id}{ext}"
    dest_path = os.path.join("data", dest_filename)

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    size_mb = round(os.path.getsize(dest_path) / (1024 * 1024), 2)
    duration_s = None
    fps = None
    res = None
    try:
        import cv2
        cap = cv2.VideoCapture(dest_path)
        if cap.isOpened():
            fps = round(cap.get(cv2.CAP_PROP_FPS) or 30.0, 1)
            total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            duration_s = round(total_f / max(1.0, fps), 1) if fps > 0 else 0.0
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            res = f"{w}x{h}"
            cap.release()
    except Exception:
        pass

    return {
        "video_id": video_id,
        "original_filename": file.filename,
        "saved_path": dest_path.replace("\\", "/"),
        "size_mb": size_mb,
        "duration_seconds": duration_s,
        "fps": fps,
        "resolution": res,
        "status": "UPLOADED",
    }


@router.post("/video/process", response_model=JobStatusResponse)
async def process_video(
    req: ProcessVideoRequest,
    background_tasks: BackgroundTasks,
):
    """Enqueues a video processing task using BoT-SORT / ByteTrack."""
    video_id = req.video_id or f"job_{uuid.uuid4().hex[:8]}"
    video_path = req.video_path

    # If no path given, look for files in data/ directory
    if not video_path:
        data_files = [os.path.join("data", f) for f in os.listdir("data") if f.endswith((".mp4", ".avi", ".mov", ".mkv"))] if os.path.exists("data") else []
        if not data_files:
            raise HTTPException(status_code=400, detail="No video file provided and data/ directory is empty.")
        video_path = data_files[0]

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"Video file not found at: {video_path}")

    job_status = PipelineStatus(video_id=video_id, status="QUEUED")
    JOB_REGISTRY[video_id] = job_status

    # Capture current running event loop for real-time WebSocket frames from background thread
    main_loop = asyncio.get_running_loop()

    # Start asynchronous background execution
    background_tasks.add_task(_run_pipeline_job, video_path, job_status, req, main_loop)

    return JobStatusResponse(
        video_id=video_id,
        status="QUEUED",
        progress_percent=0.0,
        current_frame=0,
        total_frames=0,
        fps_processing=0.0,
        active_tracks=0,
        total_unique_tracks=0,
    )


@router.get("/video/{video_id}/status", response_model=JobStatusResponse)
async def get_video_status(video_id: str):
    """Polls processing progress (0-100%) and output file paths."""
    if video_id not in JOB_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Job {video_id} not found.")

    st = JOB_REGISTRY[video_id]
    return JobStatusResponse(
        video_id=st.video_id,
        status=st.status,
        progress_percent=st.progress_percent,
        current_frame=st.current_frame,
        total_frames=st.total_frames,
        fps_processing=st.fps_processing,
        active_tracks=st.active_tracks,
        total_unique_tracks=st.total_unique_tracks,
        output_files=st.output_files,
        summary=st.summary,
        error_message=st.error_message,
    )


# ── Tracks & Trajectories Queries ──────────────────────────────────────────────

@router.get("/trajectories")
async def get_all_trajectories(session_id: Optional[str] = None):
    """Retrieves all tracked objects along with their complete spatial trails for the 2D visualizer."""
    trajs = storage.get_all_trajectories_with_trails(session_id=session_id)
    return {"total": len(trajs), "trajectories": trajs}


@router.delete("/trajectories")
async def clear_trajectories():
    """Clears all stored tracks and trajectory history from SQLite persistence."""
    storage.clear_all()
    return {"status": "SUCCESS", "message": "All trajectories and tracks cleared."}



@router.get("/tracks")
async def list_tracks(session_id: Optional[str] = None):
    """Retrieves all tracked objects from SQLite persistence."""
    tracks = storage.get_all_tracks(session_id=session_id)
    return {"total": len(tracks), "tracks": tracks}


@router.get("/tracks/{track_id}")
async def get_track_detail(track_id: int):
    """Retrieves metadata and summary metrics for a specific track ID."""
    track = storage.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track ID #{track_id} not found.")
    return track


@router.get("/tracks/{track_id}/trajectory")
async def get_track_trajectory(track_id: int):
    """Retrieves complete spatial-temporal coordinate trajectory history for a track."""
    points = storage.get_trajectory_points(track_id)
    if not points:
        raise HTTPException(status_code=404, detail=f"No trajectory points found for #{track_id}.")
    return {"track_id": track_id, "total_points": len(points), "points": points}


# ── Analytics Foundation ───────────────────────────────────────────────────────

@router.get("/analytics/summary")
async def get_analytics_summary():
    """Returns high-level overview of unique tracks and class distributions."""
    tracks = storage.get_all_tracks()
    class_counts = {}
    total_speed = 0.0
    for t in tracks:
        c = t.get("normalized_class", "UNKNOWN")
        class_counts[c] = class_counts.get(c, 0) + 1
        total_speed += t.get("average_speed", 0.0)

    avg_speed = round(total_speed / len(tracks), 2) if tracks else 0.0

    return {
        "total_unique_tracks": len(tracks),
        "average_speed": avg_speed,
        "speed_unit": "px/s (Relative)",
        "class_distribution": class_counts,
    }


@router.get("/analytics/density")
async def get_density_metric():
    """Returns spatial density measurement."""
    tracks = storage.get_all_tracks()
    return {
        "total_tracks": len(tracks),
        "density_level": "MODERATE" if len(tracks) < 50 else "HEAVY",
        "description": "Spatial road-user concentration over surveillance viewport.",
    }


@router.get("/analytics/speed")
async def get_speed_metric():
    """Returns speed distribution statistics."""
    tracks = storage.get_all_tracks()
    speeds = [t.get("average_speed", 0.0) for t in tracks if t.get("average_speed", 0.0) > 0]
    avg = round(sum(speeds) / len(speeds), 2) if speeds else 0.0

    return {
        "average_speed": avg,
        "unit": "px/s",
        "label": "Relative speed",
        "sampled_entities": len(speeds),
    }


# ── Telemetry & FlytBase DiaB Integrations ─────────────────────────────────────

@router.get("/telemetry")
async def get_telemetry():
    """Returns real-time drone aerial telemetry."""
    return flytbase_client.get_telemetry()


@router.get("/flytbase/status")
async def get_flytbase_status():
    """Returns FlytBase Drone-in-a-Box connection status."""
    st = flytbase_client.get_vehicle_state()
    stream_info = flytbase_client.get_video_stream()
    return {
        "vehicle_state": {
            "vehicle_id": st.vehicle_id,
            "mode": st.mode,
            "battery_pct": st.battery_pct,
            "armed": st.armed,
            "in_air": st.is_in_air,
            "current_lat": st.current_lat,
            "current_lng": st.current_lng,
            "altitude_agl": st.current_alt_agl,
            "heading": st.heading_deg,
            "speed_mps": st.speed_mps,
            "gimbal_pitch": st.gimbal_pitch_deg,
            "dock_id": st.dock_id,
            "connection_status": st.connection_status,
        },
        "video_stream": stream_info,
        "mode": flytbase_client.mode,
    }


@router.post("/flytbase/mission")
async def execute_mission(req: MissionRequest):
    """Submits and triggers an autonomous FlytBase mission plan."""
    mission_id = req.mission_id or f"mission_{uuid.uuid4().hex[:6]}"
    plan = FlytBaseMissionPlan(
        mission_id=mission_id,
        vehicle_id=flytbase_client.vehicle_id,
        dock_id="DOCK-01",
        waypoints=[
            FlytBaseWaypoint(lat=w.lat, lng=w.lng, altitude=w.altitude, speed=w.speed, action=w.action)
            for w in req.waypoints
        ],
        gimbal_pitch=req.gimbal_pitch,
    )
    success = flytbase_client.execute_mission(plan)
    return {"success": success, "mission_id": mission_id, "waypoint_count": len(req.waypoints)}


@router.post("/flytbase/gimbal")
async def set_gimbal(req: GimbalRequest):
    """Adjusts drone payload camera gimbal orientation."""
    success = flytbase_client.set_gimbal(pitch=req.pitch, roll=req.roll, yaw=req.yaw)
    return {"success": success, "pitch": req.pitch, "roll": req.roll, "yaw": req.yaw}


# ── Output Artifacts & Video Streaming ──────────────────────────────────────────

@router.get("/outputs")
async def list_output_videos():
    """Lists generated annotated video MP4s and artifacts in outputs/ directory."""
    files = []
    if os.path.exists("outputs"):
        for f in os.listdir("outputs"):
            if f.lower().endswith(".mp4"):
                p = os.path.join("outputs", f)
                size_mb = round(os.path.getsize(p) / (1024 * 1024), 2)
                files.append({
                    "filename": f,
                    "url": f"/api/outputs/{f}",
                    "size_mb": size_mb,
                })
    return {"outputs": files}


@router.get("/outputs/{filename}")
async def download_output_file(filename: str):
    """Serves generated MP4, JSONL, CSV, or JSON artifact with correct MIME type."""
    file_path = os.path.join("outputs", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "video/mp4" if filename.lower().endswith(".mp4") else (
        "application/json" if filename.lower().endswith((".json", ".jsonl")) else (
            "text/csv" if filename.lower().endswith(".csv") else None
        )
    )
    return FileResponse(file_path, media_type=media_type)
