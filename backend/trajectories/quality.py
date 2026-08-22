"""
Kinematic Measurement Quality Control & Reliability Flagging
Flags unreliable velocity, acceleration, or trajectory measurements caused by:
  - Missing or invalid ground-plane calibration
  - Insufficient tracking history (< 5 frames)
  - Teleportation / tracking association jumps
  - Timestamp jitter / zero dt
"""

from enum import Enum
from typing import NamedTuple, Optional, List


class KinematicQualityFlag(str, Enum):
    VALID_HIGH_CONFIDENCE = "VALID_HIGH_CONFIDENCE"
    UNRELIABLE_MISSING_CALIBRATION = "UNRELIABLE_MISSING_CALIBRATION"
    UNRELIABLE_INSUFFICIENT_HISTORY = "UNRELIABLE_INSUFFICIENT_HISTORY"
    UNRELIABLE_TIMESTAMP_JITTER = "UNRELIABLE_TIMESTAMP_JITTER"
    UNRELIABLE_TRACKING_JUMP = "UNRELIABLE_TRACKING_JUMP"
    UNRELIABLE_EXTREME_ACCELERATION = "UNRELIABLE_EXTREME_ACCELERATION"


class QualityAssessment(NamedTuple):
    flag: KinematicQualityFlag
    is_reliable: bool
    description: str


class KinematicQualityAssessor:
    """
    Evaluates metric kinematic measurements against physical operational constraints.
    """

    MAX_METRIC_SPEED_MPS: float = 65.0      # ~234 km/h (beyond realistic urban traffic)
    MAX_METRIC_ACCEL_MPS2: float = 14.0     # ~1.4G (beyond standard vehicle braking/accel)
    MIN_TRACK_OBSERVATIONS: int = 5         # Minimum frames required to establish kinematics

    @classmethod
    def assess(
        cls,
        is_calibrated: bool,
        history_length: int,
        dt: float,
        speed_mps: Optional[float],
        accel_mps2: Optional[float],
        jump_detected: bool = False,
    ) -> QualityAssessment:
        """
        Assesses instantaneous kinematic reliability for a tracked entity.
        """
        if not is_calibrated:
            return QualityAssessment(
                flag=KinematicQualityFlag.UNRELIABLE_MISSING_CALIBRATION,
                is_reliable=False,
                description="Ground plane is uncalibrated. Metrics are relative pixel velocities.",
            )

        if jump_detected:
            return QualityAssessment(
                flag=KinematicQualityFlag.UNRELIABLE_TRACKING_JUMP,
                is_reliable=False,
                description="Spatial jump detected across disconnected road zones.",
            )

        if dt <= 0.0001 or dt > 2.0:
            return QualityAssessment(
                flag=KinematicQualityFlag.UNRELIABLE_TIMESTAMP_JITTER,
                is_reliable=False,
                description=f"Irregular timestamp delta (dt={dt:.3f}s).",
            )

        if history_length < cls.MIN_TRACK_OBSERVATIONS:
            return QualityAssessment(
                flag=KinematicQualityFlag.UNRELIABLE_INSUFFICIENT_HISTORY,
                is_reliable=False,
                description=f"Track history stabilizing ({history_length}/{cls.MIN_TRACK_OBSERVATIONS} observations).",
            )

        if speed_mps is not None and speed_mps > cls.MAX_METRIC_SPEED_MPS:
            return QualityAssessment(
                flag=KinematicQualityFlag.UNRELIABLE_TRACKING_JUMP,
                is_reliable=False,
                description=f"Unrealistic ground velocity ({speed_mps * 3.6:.1f} km/h).",
            )

        if accel_mps2 is not None and abs(accel_mps2) > cls.MAX_METRIC_ACCEL_MPS2:
            return QualityAssessment(
                flag=KinematicQualityFlag.UNRELIABLE_EXTREME_ACCELERATION,
                is_reliable=False,
                description=f"Extreme acceleration spike ({accel_mps2:.1f} m/s²).",
            )

        return QualityAssessment(
            flag=KinematicQualityFlag.VALID_HIGH_CONFIDENCE,
            is_reliable=True,
            description="Verified high-confidence metric kinematics.",
        )
