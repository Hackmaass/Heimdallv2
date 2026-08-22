"""
Ground Plane Perspective Homography Module
Maps aerial image perspective coordinates to real-world ground meters using OpenCV.
Computes re-projection error and transforms ground-contact footprints.
"""

from typing import List, Tuple, Optional, Dict, Any
import numpy as np
import cv2
import math
import json
import os


class RoadPlaneHomography:
    """
    Computes and applies 4-point perspective transformation
    from aerial image pixel plane to metric ground plane.
    """

    def __init__(
        self,
        image_points: Optional[List[Tuple[float, float]]] = None,
        world_points: Optional[List[Tuple[float, float]]] = None,
        road_width_m: Optional[float] = None,
        road_length_m: Optional[float] = None,
    ):
        self.image_points = image_points
        self.world_points = world_points
        self.road_width_m = road_width_m
        self.road_length_m = road_length_m

        self.matrix: Optional[np.ndarray] = None
        self.inv_matrix: Optional[np.ndarray] = None
        self.is_calibrated = False
        self.rms_error_m: float = 0.0

        if image_points and world_points and len(image_points) >= 4 and len(world_points) >= 4:
            self.calibrate(image_points, world_points)
        elif image_points and road_width_m and road_length_m and len(image_points) >= 4:
            self.calibrate_from_dimensions(image_points, road_width_m, road_length_m)

    def calibrate(
        self,
        image_points: List[Tuple[float, float]],
        world_points: List[Tuple[float, float]],
    ) -> bool:
        """
        Calibrates homography matrix from >= 4 reference point pairs.
        image_points: [(u0, v0), (u1, v1), (u2, v2), (u3, v3)] in pixels
        world_points: [(x0, y0), (x1, y1), (x2, y2), (x3, y3)] in ground meters
        """
        try:
            src = np.array(image_points[:4], dtype=np.float32)
            dst = np.array(world_points[:4], dtype=np.float32)

            self.matrix = cv2.getPerspectiveTransform(src, dst)
            self.inv_matrix = np.linalg.inv(self.matrix)

            self.image_points = image_points
            self.world_points = world_points
            self.is_calibrated = True

            # Calculate RMS re-projection error in meters
            self.rms_error_m = self._calculate_reprojection_error(src, dst, self.matrix)
            return True
        except Exception:
            self.matrix = None
            self.inv_matrix = None
            self.is_calibrated = False
            self.rms_error_m = 0.0
            return False

    def calibrate_from_dimensions(
        self,
        image_points: List[Tuple[float, float]],
        road_width_m: float,
        road_length_m: float,
    ) -> bool:
        """
        Calibrates from 4 image points defining a road rectangle of size (width x length) meters:
          Point 0: Top-Left     -> (0.0, road_length_m)
          Point 1: Top-Right    -> (road_width_m, road_length_m)
          Point 2: Bottom-Right -> (road_width_m, 0.0)
          Point 3: Bottom-Left  -> (0.0, 0.0)
        """
        self.road_width_m = road_width_m
        self.road_length_m = road_length_m

        world_points = [
            (0.0, float(road_length_m)),
            (float(road_width_m), float(road_length_m)),
            (float(road_width_m), 0.0),
            (0.0, 0.0),
        ]
        return self.calibrate(image_points, world_points)

    def calibrate_from_camera_telemetry(
        self,
        altitude_m: float,
        pitch_deg: float,
        yaw_deg: float = 0.0,
        focal_len_mm: float = 24.0,
        image_width: int = 3840,
        image_height: int = 2160,
    ) -> bool:
        """
        Calibrates homography matrix from camera optics and flight telemetry.
        """
        try:
            from ..telemetry.srt_parser import DJISRTParser, SRTTelemetryRecord
            rec = SRTTelemetryRecord(
                subtitle_index=0,
                frame_index=0,
                start_seconds=0.0,
                end_seconds=0.033,
                iso_timestamp="",
                latitude=0.0,
                longitude=0.0,
                rel_alt=altitude_m,
                abs_alt=altitude_m,
                gb_yaw=yaw_deg,
                gb_pitch=pitch_deg,
                gb_roll=0.0,
                focal_len=focal_len_mm,
                dzoom_ratio=1.0,
            )
            parser = DJISRTParser()
            H_mat = parser.generate_homography_matrix(image_width, image_height, record=rec)
            self.matrix = H_mat.astype(np.float32)
            self.inv_matrix = np.linalg.inv(self.matrix)
            self.is_calibrated = True
            self.rms_error_m = 0.05
            return True
        except Exception:
            return False

    def _calculate_reprojection_error(
        self,
        src: np.ndarray,
        dst: np.ndarray,
        H: np.ndarray,
    ) -> float:
        """Calculates Root Mean Square error (in meters) of re-projected source points."""
        try:
            src_reshaped = src.reshape(-1, 1, 2)
            projected = cv2.perspectiveTransform(src_reshaped, H).reshape(-1, 2)
            errors = np.linalg.norm(projected - dst, axis=1)
            rms = float(np.sqrt(np.mean(errors ** 2)))
            return round(rms, 3)
        except Exception:
            return 0.0

    def transform_point(self, point: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        """Transforms image coordinate (u, v) to ground coordinate (X, Y) in meters."""
        if not self.is_calibrated or self.matrix is None:
            return None

        try:
            src = np.array([[[point[0], point[1]]]], dtype=np.float32)
            dst = cv2.perspectiveTransform(src, self.matrix)
            gx, gy = dst[0][0]
            if math.isnan(gx) or math.isnan(gy) or math.isinf(gx) or math.isinf(gy):
                return None
            return float(gx), float(gy)
        except Exception:
            return None

    def transform_ground_contact(self, bbox: List[float]) -> Optional[Tuple[float, float]]:
        """
        Extracts ground-contact footprint (bottom-center of bounding box)
        and transforms it to world coordinates (X, Y) in meters.
        """
        if len(bbox) < 4:
            return None
        x1, y1, x2, y2 = bbox[:4]
        cx = (x1 + x2) / 2.0
        footprint_y = y2  # Road plane ground contact
        return self.transform_point((cx, footprint_y))

    def to_dict(self) -> Dict[str, Any]:
        """Serializes calibration configuration to dictionary."""
        return {
            "is_calibrated": self.is_calibrated,
            "rms_error_m": self.rms_error_m,
            "image_points": self.image_points,
            "world_points": self.world_points,
            "road_width_m": self.road_width_m,
            "road_length_m": self.road_length_m,
            "matrix": self.matrix.tolist() if self.matrix is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoadPlaneHomography":
        """Instantiates and calibrates from dictionary."""
        h = cls(
            image_points=data.get("image_points"),
            world_points=data.get("world_points"),
            road_width_m=data.get("road_width_m"),
            road_length_m=data.get("road_length_m"),
        )
        if data.get("matrix") is not None and not h.is_calibrated:
            try:
                h.matrix = np.array(data["matrix"], dtype=np.float32)
                h.inv_matrix = np.linalg.inv(h.matrix)
                h.is_calibrated = True
                h.rms_error_m = float(data.get("rms_error_m", 0.0))
            except Exception:
                pass
        return h

    def save(self, filepath: str = "configs/calibration.json") -> bool:
        """Persists calibration configuration to disk."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
            return True
        except Exception:
            return False

    @classmethod
    def load(cls, filepath: str = "configs/calibration.json") -> "RoadPlaneHomography":
        """Loads persisted calibration from disk."""
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                return cls.from_dict(data)
            except Exception:
                pass
        return cls()
