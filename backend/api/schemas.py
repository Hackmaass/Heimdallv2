"""
FastAPI Request & Response Pydantic Schemas (Level 1 + Level 2 Extended Models)
"""

from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field


class ProcessVideoRequest(BaseModel):
    video_path: Optional[str] = Field(None, description="Local path to video file or URL")
    video_id: Optional[str] = Field(None, description="Unique job ID; auto-generated if omitted")
    tracker_type: Optional[str] = Field("botsort", description="botsort or bytetrack")
    model_name: Optional[str] = Field("yolov8s-visdrone.pt", description="YOLO model path or identifier (VisDrone recommended for aerial surveillance)")
    confidence_threshold: Optional[float] = Field(0.25, ge=0.0, le=1.0)
    process_every_n_frames: Optional[int] = Field(1, ge=1)
    save_annotated_video: Optional[bool] = True
    duration_seconds: Optional[float] = Field(None, ge=0.5, description="Maximum duration in seconds to process (null for full video)")
    start_seconds: Optional[float] = Field(0.0, ge=0.0, description="Start offset in seconds")
    max_frames: Optional[int] = Field(None, ge=1, description="Direct max frames override")
    enable_sahi: Optional[bool] = Field(False, description="Enable SAHI sliced inference for small object detection in 4K footage")
    sahi_slice_size: Optional[int] = Field(960, ge=320, le=1920, description="Slice tile size in pixels for SAHI")


class JobStatusResponse(BaseModel):
    video_id: str
    status: str  # "QUEUED", "PROCESSING", "COMPLETED", "FAILED"
    progress_percent: float
    current_frame: int
    total_frames: int
    fps_processing: float = 0.0
    active_tracks: int = 0
    total_unique_tracks: int = 0
    output_files: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class CalibrationRequest(BaseModel):
    image_points: List[List[float]] = Field(..., min_length=4, max_length=4, description="4 reference points in image pixels [[u0,v0], [u1,v1], [u2,v2], [u3,v3]]")
    road_width_m: Optional[float] = Field(None, ge=1.0, description="Real-world road width in meters")
    road_length_m: Optional[float] = Field(None, ge=1.0, description="Real-world road length in meters")
    world_points: Optional[List[List[float]]] = Field(None, min_length=4, max_length=4, description="Explicit 4 ground coordinates [[x0,y0], [x1,y1], [x2,y2], [x3,y3]] in meters")


class CalibrationResponse(BaseModel):
    status: str
    is_calibrated: bool
    rms_error_m: float
    road_width_m: Optional[float] = None
    road_length_m: Optional[float] = None
    image_points: Optional[List[List[float]]] = None
    world_points: Optional[List[List[float]]] = None


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


class SpatialCalibrationRequest(BaseModel):
    anchor_lat: float = Field(..., description="WGS-84 Latitude of ground control reference point")
    anchor_lon: float = Field(..., description="WGS-84 Longitude of ground control reference point")
    intersection_name: Optional[str] = Field("Primary Intersection", description="Descriptive name")
    is_calibrated: Optional[bool] = Field(True, description="Mark as verified ground control calibration")


class SpatialCalibrationResponse(BaseModel):
    status: str
    is_calibrated: bool
    anchor_lat: float
    anchor_lon: float
    confidence_flag: str
    message: str

