"""
FlytBase API Data Models & Command Schemas
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class FlytBaseWaypoint:
    lat: float
    lng: float
    altitude: float  # meters AGL
    speed: float = 12.0  # m/s
    action: str = "flythrough"  # "takeoff", "flythrough", "orbit_roi", "land_dock"


@dataclass
class FlytBaseMissionPlan:
    mission_id: str
    vehicle_id: str
    dock_id: str
    waypoints: List[FlytBaseWaypoint]
    gimbal_pitch: float = -45.0
    auto_start: bool = True
    failsafe_rtb: bool = True


@dataclass
class VehicleState:
    vehicle_id: str
    mode: str  # "IDLE_DOCKED", "TAKING_OFF", "NAVIGATING", "LOITERING", "RETURNING_HOME", "LANDING", "CHARGING"
    battery_pct: float
    armed: bool
    is_in_air: bool
    current_lat: float
    current_lng: float
    current_alt_agl: float
    heading_deg: float
    speed_mps: float
    gimbal_pitch_deg: float
    dock_id: Optional[str] = "DOCK-01"
    connection_status: str = "CONNECTED"


@dataclass
class GimbalCommand:
    pitch: float  # [-90, +30] degrees
    roll: float = 0.0
    yaw: float = 0.0  # relative or absolute degrees
    mode: str = "ANGLE"  # "ANGLE" or "RATE"
