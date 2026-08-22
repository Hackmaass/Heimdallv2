"""
Ground Plane Perspective Homography Module
Maps aerial image perspective coordinates to real-world ground meters.
"""

from typing import List, Tuple, Optional
import numpy as np
import cv2


class RoadPlaneHomography:
    """
    Computes and applies 4-point perspective transformation
    from aerial image pixel plane to metric ground plane.
    """

    def __init__(
        self,
        image_points: Optional[List[Tuple[float, float]]] = None,
        world_points: Optional[List[Tuple[float, float]]] = None,
    ):
        self.image_points = image_points
        self.world_points = world_points
        self.matrix: Optional[np.ndarray] = None
        self.is_calibrated = False

        if image_points and world_points and len(image_points) >= 4 and len(world_points) >= 4:
            self.calibrate(image_points, world_points)

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
            self.image_points = image_points
            self.world_points = world_points
            self.is_calibrated = True
            return True
        except Exception:
            self.matrix = None
            self.is_calibrated = False
            return False

    def transform_point(self, point: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        """Transforms pixel centroid (cx, cy) to ground coordinate (x, y) in meters."""
        if not self.is_calibrated or self.matrix is None:
            return None

        try:
            src = np.array([[[point[0], point[1]]]], dtype=np.float32)
            dst = cv2.perspectiveTransform(src, self.matrix)
            gx, gy = dst[0][0]
            return float(gx), float(gy)
        except Exception:
            return None
