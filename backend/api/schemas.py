"""
FastAPI Request & Response Pydantic Schemas
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ProcessVideoRequest(BaseModel):
    video_path: Optional[str] = Field(None, description="Local path to video file or URL")
    video_id: Optional[str] = Field(None, description="Unique job ID; auto-generated if omitted")
    tracker_type: Optional[str] = Field("botsort", description="botsort or bytetrack")
    model_name: Optional[str] = Field("yolov8n.pt", description="YOLO model path or identifier")
    confidence_threshold: Optional[float] = Field(0.25, ge=0.0, le=1.0)
    process_every_n_frames: Optional[int] = Field(1, ge=1)
    save_annotated_video: Optional[bool] = True
    duration_seconds: Optional[float] = Field(None, ge=0.5, description="Maximum duration in seconds to process (null for full video)")
    start_seconds: Optional[float] = Field(0.0, ge=0.0, description="Start offset in seconds")
    max_frames: Optional[int] = Field(None, ge=1, description="Direct max frames override")


class JobStatusResponse(BaseModel):
    video_id: str
    status: str  # "QUEUED", "PROCESSING", "COMPLETED", "FAILED"
    progress_percent: float
    current_frame: int
    total_frames: int
    fps_processing: float
    active_tracks: int
    total_unique_tracks: int
    output_files: Dict[str, str] = {}
    summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class GimbalRequest(BaseModel):
    pitch: float = Field(..., ge=-90.0, le=30.0, description="Pitch angle in degrees")
    roll: float = Field(0.0, description="Roll angle in degrees")
    yaw: float = Field(0.0, description="Yaw angle in degrees")


class WaypointSchema(BaseModel):
    lat: float
    lng: float
    altitude: float = 60.0
    speed: float = 12.0
    action: str = "flythrough"


class MissionRequest(BaseModel):
    mission_id: Optional[str] = None
    waypoints: List[WaypointSchema]
    gimbal_pitch: float = -45.0
