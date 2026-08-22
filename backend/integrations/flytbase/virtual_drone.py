"""
Virtual Drone Simulation Abstraction for FlytBase Workflows
"""

import time
import math
from typing import List, Optional
from .models import VehicleState, FlytBaseWaypoint, FlytBaseMissionPlan, GimbalCommand


class VirtualDrone:
    """
    Simulates a physical drone executing FlytBase flight missions,
    gimbal maneuvers, and automated docking behaviors.
    """

    def __init__(
        self,
        vehicle_id: str = "VIRTUAL-DRONE-01",
        base_lat: float = 18.5308,
        base_lng: float = 73.8475,
        dock_id: str = "DOCK-01",
    ):
        self.vehicle_id = vehicle_id
        self.base_lat = base_lat
        self.base_lng = base_lng
        self.dock_id = dock_id

        self.current_lat = base_lat
        self.current_lng = base_lng
        self.current_alt = 0.0
        self.heading = 0.0
        self.speed = 0.0
        self.battery = 98.0
        self.mode = "IDLE_DOCKED"
        self.gimbal_pitch = 0.0
        self.gimbal_yaw = 0.0

        self.active_waypoints: List[FlytBaseWaypoint] = []
        self.current_wp_idx = 0
        self._last_tick = time.time()

    def get_state(self) -> VehicleState:
        return VehicleState(
            vehicle_id=self.vehicle_id,
            mode=self.mode,
            battery_pct=round(self.battery, 1),
            armed=(self.mode not in ["IDLE_DOCKED", "CHARGING"]),
            is_in_air=(self.current_alt > 2.0),
            current_lat=round(self.current_lat, 6),
            current_lng=round(self.current_lng, 6),
            current_alt_agl=round(self.current_alt, 1),
            heading_deg=round(self.heading, 1),
            speed_mps=round(self.speed, 1),
            gimbal_pitch_deg=round(self.gimbal_pitch, 1),
            dock_id=self.dock_id,
            connection_status="CONNECTED (SIMULATED)",
        )

    def execute_navigation(self, lat: float, lng: float, alt: float = 60.0, speed: float = 12.0) -> bool:
        """Dispatches drone directly to target GPS coordinates."""
        self.mode = "NAVIGATING"
        self.current_alt = alt
        self.speed = speed
        self.active_waypoints = [FlytBaseWaypoint(lat=lat, lng=lng, altitude=alt, speed=speed)]
        self.current_wp_idx = 0
        return True

    def execute_mission(self, plan: FlytBaseMissionPlan) -> bool:
        """Loads and executes multi-waypoint mission plan."""
        self.active_waypoints = list(plan.waypoints)
        self.current_wp_idx = 0
        self.mode = "NAVIGATING"
        self.gimbal_pitch = plan.gimbal_pitch
        return True

    def set_gimbal(self, cmd: GimbalCommand) -> bool:
        """Adjusts camera gimbal orientation."""
        self.gimbal_pitch = max(-90.0, min(30.0, cmd.pitch))
        self.gimbal_yaw = cmd.yaw
        return True

    def return_to_home(self) -> bool:
        """Initiates autonomous return to launch/dock."""
        self.mode = "RETURNING_HOME"
        self.active_waypoints = [FlytBaseWaypoint(lat=self.base_lat, lng=self.base_lng, altitude=50.0)]
        self.current_wp_idx = 0
        return True
