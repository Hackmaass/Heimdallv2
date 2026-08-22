"""
Spatial Georeferencer Module (Level 4 Spatial Grounding)
Transforms 2D video image points into real-world geographic coordinates (WGS-84 Latitude / Longitude)
using synchronized DJI SRT flight telemetry and 3D camera ray-plane intersection.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Dict, Any, List
import numpy as np

from ..telemetry.srt_parser import SRTTelemetryRecord, DJISRTParser


class SpatialConfidenceFlag(str, Enum):
    """Integrity and calibration confidence level for geographic coordinates."""
    CALIBRATED = "HIGH_CONFIDENCE (CALIBRATED)"
    TELEMETRY_ESTIMATED = "MEDIUM_CONFIDENCE (TELEMETRY_ESTIMATED)"
    UNCALIBRATED = "LOW_CONFIDENCE (UNCALIBRATED)"


@dataclass
class GeoreferencedPoint:
    """A geographically grounded point in SI metric space and WGS-84 geodetic coordinates."""
    latitude: float
    longitude: float
    world_x_m: float
    world_y_m: float
    confidence_flag: str
    altitude_m: float = 0.0


class SpatialGeoreferencer:
    """
    High-precision camera-to-ground georeferencer.
    Translates pixel coordinates (u, v) -> ground metric displacement (X, Y) -> WGS-84 (Lat, Lon).
    """

    # WGS-84 Ellipsoid constants
    WGS84_A = 6378137.0         # Semi-major axis in meters
    WGS84_E2 = 0.00669437999014 # Square of eccentricity

    def __init__(
        self,
        srt_parser: Optional[DJISRTParser] = None,
        anchor_lat: float = 18.566227,
        anchor_lon: float = 73.771846,
        is_homography_calibrated: bool = False,
    ):
        self.srt_parser = srt_parser
        self.anchor_lat = anchor_lat
        self.anchor_lon = anchor_lon
        self.is_homography_calibrated = is_homography_calibrated

    @staticmethod
    def meters_per_degree(latitude_deg: float) -> Tuple[float, float]:
        """
        Computes accurate meters per degree of latitude and longitude at a given latitude
        using the WGS-84 reference ellipsoid formula.
        Returns: (meters_per_lat_deg, meters_per_lon_deg)
        """
        phi = math.radians(latitude_deg)
        # Meridian radius of curvature
        m_lat = 111132.954 - 559.822 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
        # Prime vertical radius of curvature
        m_lon = (math.pi * SpatialGeoreferencer.WGS84_A * math.cos(phi)) / (
            180.0 * math.sqrt(1.0 - SpatialGeoreferencer.WGS84_E2 * math.sin(phi) ** 2)
        )
        return m_lat, m_lon

    @staticmethod
    def metric_to_wgs84(
        ref_lat: float,
        ref_lon: float,
        dx_meters: float,
        dy_meters: float,
    ) -> Tuple[float, float]:
        """
        Converts local ENU metric offsets (dx = East meters, dy = North meters)
        relative to reference (ref_lat, ref_lon) into geodetic (lat, lon).
        """
        m_lat, m_lon = SpatialGeoreferencer.meters_per_degree(ref_lat)
        delta_lat = dy_meters / max(1.0, m_lat)
        delta_lon = dx_meters / max(1.0, m_lon)
        return float(round(ref_lat + delta_lat, 7)), float(round(ref_lon + delta_lon, 7))

    @staticmethod
    def wgs84_to_metric(
        ref_lat: float,
        ref_lon: float,
        target_lat: float,
        target_lon: float,
    ) -> Tuple[float, float]:
        """
        Converts target (lat, lon) into local metric offsets (East meters, North meters)
        relative to reference (ref_lat, ref_lon).
        """
        m_lat, m_lon = SpatialGeoreferencer.meters_per_degree(ref_lat)
        dy = (target_lat - ref_lat) * m_lat
        dx = (target_lon - ref_lon) * m_lon
        return float(round(dx, 3)), float(round(dy, 3))

    def project_pixel_to_wgs84(
        self,
        u: float,
        v: float,
        image_width: int = 1920,
        image_height: int = 1080,
        frame_index: int = 0,
        record: Optional[SRTTelemetryRecord] = None,
    ) -> GeoreferencedPoint:
        """
        Projects an image pixel footprint (u, v) to ground metric (X, Y) and geodetic WGS-84 (lat, lon).
        """
        rec = record
        if rec is None and self.srt_parser:
            rec = self.srt_parser.get_record_by_frame(frame_index)

        confidence = SpatialConfidenceFlag.UNCALIBRATED.value

        if rec:
            drone_lat = rec.latitude if rec.latitude != 0.0 else self.anchor_lat
            drone_lon = rec.longitude if rec.longitude != 0.0 else self.anchor_lon

            # Use 3D ray-plane intersection from srt_parser
            gx, gy = self.srt_parser.pixel_to_ground_meters(
                u, v, image_width, image_height, record=rec, frame_index=frame_index
            )

            # Note: gx is East-meters, gy is North-meters relative to drone nadir
            lat, lon = self.metric_to_wgs84(drone_lat, drone_lon, gx, gy)
            confidence = (
                SpatialConfidenceFlag.CALIBRATED.value
                if self.is_homography_calibrated
                else SpatialConfidenceFlag.TELEMETRY_ESTIMATED.value
            )
            return GeoreferencedPoint(
                latitude=lat,
                longitude=lon,
                world_x_m=gx,
                world_y_m=gy,
                confidence_flag=confidence,
                altitude_m=0.0,
            )

        # Fallback without telemetry: use anchor lat/lon and optical scale
        cx = image_width / 2.0
        cy = image_height / 2.0
        gx = (u - cx) * 0.05
        gy = -(v - cy) * 0.05
        lat, lon = self.metric_to_wgs84(self.anchor_lat, self.anchor_lon, gx, gy)
        conf = (
            SpatialConfidenceFlag.CALIBRATED.value
            if self.is_homography_calibrated
            else SpatialConfidenceFlag.UNCALIBRATED.value
        )
        return GeoreferencedPoint(
            latitude=lat,
            longitude=lon,
            world_x_m=gx,
            world_y_m=gy,
            confidence_flag=conf,
            altitude_m=0.0,
        )
