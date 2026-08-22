"""
Unit Tests for FlytBase Integration & Virtual Drone
"""

import pytest
from backend.integrations.flytbase.client import FlytBaseClient
from backend.integrations.flytbase.models import FlytBaseMissionPlan, FlytBaseWaypoint


def test_flytbase_mock_client():
    client = FlytBaseClient(mode="mock")
    assert client.is_mock is True

    # State Query
    state = client.get_vehicle_state()
    assert state.vehicle_id == "VIRTUAL-DRONE-01"
    assert state.mode == "IDLE_DOCKED"
    assert state.battery_pct > 90.0

    # Navigation command
    ok = client.execute_navigation(lat=18.5204, lng=73.8567, alt=60.0, speed=12.0)
    assert ok is True
    st_after = client.get_vehicle_state()
    assert st_after.mode == "NAVIGATING"

    # Gimbal command
    gimbal_ok = client.set_gimbal(pitch=-45.0, yaw=90.0)
    assert gimbal_ok is True
    assert client.get_vehicle_state().gimbal_pitch_deg == -45.0

    # Mission execution
    plan = FlytBaseMissionPlan(
        mission_id="test_mission_01",
        vehicle_id="VIRTUAL-DRONE-01",
        dock_id="DOCK-01",
        waypoints=[
            FlytBaseWaypoint(lat=18.5308, lng=73.8475, altitude=60.0),
            FlytBaseWaypoint(lat=18.5204, lng=73.8567, altitude=45.0, action="orbit_roi"),
        ],
    )
    m_ok = client.execute_mission(plan)
    assert m_ok is True

    # Return to home
    rth_ok = client.return_to_home()
    assert rth_ok is True
    assert client.get_vehicle_state().mode == "RETURNING_HOME"
