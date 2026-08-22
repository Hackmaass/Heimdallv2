# HEIMDALLv2 — Autonomous Drone Aerial Traffic Intelligence Platform

Production-quality Computer Vision, BoT-SORT Multi-Object Tracking, Trajectory Engine, and Robotics Command Console for FlytBase Drone-in-a-Box (DiaB) Infrastructure.

---

## 1. Overview & Architecture

HEIMDALLv2 delivers an end-to-end aerial perception and telemetry closed-loop system:
- **Perception Stack**: Ultralytics YOLO / YOLOE detector abstraction with promptable zero-shot open-vocabulary support and 8-class normalized taxonomy mapping (`PERSON`, `BICYCLE`, `MOTORCYCLE`, `CAR`, `LGV`, `HGV`, `BUS`, `OTHER_VEHICLE`) with explicit uncertainty resolution.
- **Multi-Object Tracking**: BoT-SORT tracker with Camera Motion Compensation (GMC Sparse Optical Flow) and appearance ReID for drone yaw/tilt flight stability, alongside high-speed ByteTrack.
- **Trajectory & Speed Engine**: Persistent spatial-temporal motion trails, velocity vectors, heading angles, and dual-mode speed estimators (Relative pixel velocity vs 4-point Ground Plane Perspective Homography metric speed in km/h).
- **FlytBase Integration**: Complete `FlytBaseClient` implementing mission execution, waypoint corridor flight, gimbal orientation (`-90°` to `+30°`), return-to-home, and autonomous virtual drone simulation.
- **FastAPI & WebSocket Streaming**: Real-time `/ws/tracking` binary/JSON streaming engine + full REST API.
- **Tactical Command Center**: High-density aviation dark theme featuring live video HUD, 2D top-down interactive trajectory canvas, telemetry gauges, and persistent track registry.

```
Heimdallv2/
├── backend/
│   ├── ingestion/             # File, RTSP, and WebRTC video sources
│   ├── perception/            # YOLO/YOLOE detectors, BoT-SORT/ByteTrack, 8-class taxonomy
│   ├── telemetry/             # Embedded OCR, FlytBase Cloud, and Mock flight telemetry
│   ├── trajectories/          # Trajectory trails, homography, speed estimators & SQLite storage
│   ├── analytics/             # Level 1 density, speed metrics & Level 2+ extensible interfaces
│   ├── integrations/flytbase/ # FlytBase Cloud Client & Virtual Drone simulation
│   ├── reasoning/             # VLM / LLM physical scene state generator & Agent tool interface
│   ├── api/                   # FastAPI route handlers & WebSocket broadcaster
│   ├── pipeline.py            # End-to-end CV processing orchestrator
│   └── main.py                # Server entrypoint
│
├── frontend/                  # Tactical Command Center UI (HTML5, Canvas, CSS3, JS)
├── configs/                   # default.yaml, botsort.yaml, bytetrack.yaml
├── data/                      # Input video footage
├── outputs/                   # Processed MP4, JSONL, CSV, JSON, and SQLite database
├── scripts/                   # CLI runner & synthetic video generator
├── tests/                     # Comprehensive Pytest suite
└── README.md
```

---

## 2. Installation & Environment Setup

### Prerequisites
- Python 3.10+ (Tested on Python 3.13 / 3.14)
- (Optional) NVIDIA GPU with CUDA for accelerated batch inference

### Setup Steps
```bash
# 1. Enter Heimdallv2 directory
cd Heimdallv2

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux / macOS:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Initialize configuration
cp .env.example .env
```

---

## 3. Running the Server & Web Command Center

Start the FastAPI server (incorporating REST APIs, WebSocket streaming, and static dashboard hosting):

```bash
python -m backend.main
```

Access Points:
- **Command Center Dashboard**: `http://localhost:8000/`
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **Real-Time WebSocket Stream**: `ws://localhost:8000/ws/tracking`

---

## 4. Processing Video via CLI Pipeline

Process any aerial drone footage directly from the command line:

```bash
# Run with BoT-SORT tracker (Default for aerial video with camera motion)
python -m scripts.run_pipeline --video data/drone_test.mp4 --tracker botsort --conf 0.25

# Run with ByteTrack (High-speed alternative)
python -m scripts.run_pipeline --video data/drone_test.mp4 --tracker bytetrack --conf 0.30

# Run with open-vocabulary model
python -m scripts.run_pipeline --video data/drone_test.mp4 --model yolov8s-world.pt
```

---

## 5. Output Artifacts Generated

Every processed video session writes structured outputs to `outputs/`:
1. `outputs/{video_id}_annotated.mp4`: Video with bounding boxes, track IDs, color-coded trajectory trails, and top OSD flight telemetry banner.
2. `outputs/{video_id}_tracks.jsonl`: Line-delimited JSON of every per-frame observation.
3. `outputs/{video_id}_tracks.csv`: Structured tabular CSV of all track coordinates, velocities, and headings.
4. `outputs/{video_id}_trajectories.json`: Hierarchical JSON of persistent tracks with full coordinate history trails.
5. `outputs/{video_id}_summary.json`: High-level session analytics (duration, unique tracks, class breakdown, average traffic speed).
6. `outputs/heimdall.db`: Relational SQLite database for instant SQL queries.

---

## 6. FlytBase Drone-in-a-Box Integration

Configure credentials in `.env`:
```env
FLYTBASE_MODE=cloud
FLYTBASE_API_URL=https://api.flytbase.com/v1
FLYTBASE_API_KEY=your_flytbase_api_key_here
FLYTBASE_VEHICLE_ID=DRONE-PUNE-01
```

If API credentials are empty or omitted:
```env
FLYTBASE_MODE=mock
```
Heimdallv2 automatically engages `VirtualDrone`, simulating autonomous takeoff, navigation corridors at 60m AGL, camera gimbal pitch adjustments, and return-to-home docking.

---

## 7. Ground Plane Homography & Metric Speed Calibration

To enable real-world ground speed ($km/h$) rather than relative pixel speed ($px/s$), supply 4 image pixel coordinates and their corresponding ground meter coordinates in `configs/default.yaml`:

```yaml
homography:
  enabled: true
  image_points:
    - [240, 180]
    - [1080, 180]
    - [1240, 680]
    - [80, 680]
  world_points:
    - [0, 0]
    - [50, 0]
    - [50, 40]
    - [0, 40]
```

---

## 8. Running Automated Tests

Run the complete test suite across taxonomy, speed estimators, trajectory engine, FlytBase mock client, analytics, and REST endpoints:

```bash
pytest tests -v
```
