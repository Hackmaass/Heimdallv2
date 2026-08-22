"""
DJI Flight Telemetry SRT Parser & Perspective Camera-to-Ground Projector
Parses synchronized DJI drone subtitle (.srt) metadata and computes:
- Real-time Drone Flight Telemetry (GPS lat/lng, altitude AGL/MSL, gimbal pitch/yaw/roll, optics)
- Analytical Perspective Homography matrix H mapping image pixels to ground meters
- Ground Sampling Distance (GSD in meters/pixel)
- Real-world GPS mapping of tracked vehicle footprints
"""

import re
import os
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
import numpy as np


@dataclass
class SRTTelemetryRecord:
    """Standardized single-frame flight telemetry extracted from DJI SRT."""
    subtitle_index: int
    frame_index: int
    start_seconds: float
    end_seconds: float
    iso_timestamp: str
    latitude: float
    longitude: float
    rel_alt: float          # Relative altitude AGL (meters above takeoff)
    abs_alt: float          # Absolute altitude MSL (meters ASL)
    gb_yaw: float           # Gimbal yaw / heading in degrees [-180, 180] or [0, 360]
    gb_pitch: float         # Gimbal pitch in degrees (-90 = nadir down, 0 = horizontal)
    gb_roll: float          # Gimbal roll in degrees
    focal_len: float        # 35mm equivalent focal length in mm (e.g. 24.0)
    dzoom_ratio: float      # Digital zoom ratio (e.g. 1.0)
    iso: int = 100
    shutter: str = "1/1000.0"
    fnum: float = 2.8


class DJISRTParser:
    """
    Parses DJI drone SRT subtitle streams and provides rapid frame/timestamp lookup
    along with analytical optical ground projection geometry.
    """

    # Regex patterns for DJI subtitle tokens
    FRAME_CNT_PATTERN = re.compile(r"FrameCnt:\s*(\d+)(?:\s+([\d\-:\.\s]+))?", re.IGNORECASE)
    TIMECODE_PATTERN = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
    
    # Value extraction patterns
    LAT_PATTERN = re.compile(r"\[latitude:\s*([\-0-9\.]+)\]", re.IGNORECASE)
    LON_PATTERN = re.compile(r"\[longitude:\s*([\-0-9\.]+)\]", re.IGNORECASE)
    REL_ALT_PATTERN = re.compile(r"rel_alt:\s*([\-0-9\.]+)", re.IGNORECASE)
    ABS_ALT_PATTERN = re.compile(r"abs_alt:\s*([\-0-9\.]+)", re.IGNORECASE)
    GB_YAW_PATTERN = re.compile(r"gb_yaw:\s*([\-0-9\.]+)", re.IGNORECASE)
    GB_PITCH_PATTERN = re.compile(r"gb_pitch:\s*([\-0-9\.]+)", re.IGNORECASE)
    GB_ROLL_PATTERN = re.compile(r"gb_roll:\s*([\-0-9\.]+)", re.IGNORECASE)
    FOCAL_LEN_PATTERN = re.compile(r"\[focal_len:\s*([\-0-9\.]+)\]", re.IGNORECASE)
    DZOOM_PATTERN = re.compile(r"\[dzoom_ratio:\s*([\-0-9\.]+)\]", re.IGNORECASE)
    ISO_PATTERN = re.compile(r"\[iso:\s*(\d+)\]", re.IGNORECASE)
    SHUTTER_PATTERN = re.compile(r"\[shutter:\s*([^\]]+)\]", re.IGNORECASE)
    FNUM_PATTERN = re.compile(r"\[fnum:\s*([\-0-9\.]+)\]", re.IGNORECASE)

    def __init__(self, srt_filepath: Optional[str] = None):
        self.filepath = srt_filepath
        self.records: List[SRTTelemetryRecord] = []
        self._frame_to_record: Dict[int, SRTTelemetryRecord] = {}
        self._timestamps: List[float] = []

        if srt_filepath and os.path.exists(srt_filepath):
            self.parse_file(srt_filepath)

    @staticmethod
    def _timecode_to_seconds(hours: int, minutes: int, seconds: int, millis: int) -> float:
        return hours * 3600.0 + minutes * 60.0 + seconds + millis / 1000.0

    def parse_file(self, filepath: str) -> int:
        """Parses a DJI SRT file into indexed telemetry records."""
        self.filepath = filepath
        self.records.clear()
        self._frame_to_record.clear()
        self._timestamps.clear()

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Split into SRT subtitle blocks (separated by double newlines)
        blocks = re.split(r"\n\s*\n", content.strip())

        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if len(lines) < 3:
                continue

            try:
                sub_idx = int(lines[0])
            except ValueError:
                continue

            # Parse timecode line
            time_match = self.TIMECODE_PATTERN.search(lines[1])
            if not time_match:
                continue

            h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, time_match.groups())
            start_s = self._timecode_to_seconds(h1, m1, s1, ms1)
            end_s = self._timecode_to_seconds(h2, m2, s2, ms2)

            text = " ".join(lines[2:])

            # Parse FrameCnt and timestamp
            frame_idx = sub_idx - 1
            iso_time = ""
            frame_match = self.FRAME_CNT_PATTERN.search(text)
            if frame_match:
                frame_idx = int(frame_match.group(1))
                if frame_match.group(2):
                    iso_time = frame_match.group(2).strip()

            # Parse GPS & Altitude
            lat_m = self.LAT_PATTERN.search(text)
            lon_m = self.LON_PATTERN.search(text)
            lat = float(lat_m.group(1)) if lat_m else 0.0
            lon = float(lon_m.group(1)) if lon_m else 0.0

            rel_alt_m = self.REL_ALT_PATTERN.search(text)
            abs_alt_m = self.ABS_ALT_PATTERN.search(text)
            rel_alt = float(rel_alt_m.group(1)) if rel_alt_m else 50.0
            abs_alt = float(abs_alt_m.group(1)) if abs_alt_m else rel_alt + 500.0

            # Parse Gimbal Orientation
            yaw_m = self.GB_YAW_PATTERN.search(text)
            pitch_m = self.GB_PITCH_PATTERN.search(text)
            roll_m = self.GB_ROLL_PATTERN.search(text)
            gb_yaw = float(yaw_m.group(1)) if yaw_m else 0.0
            gb_pitch = float(pitch_m.group(1)) if pitch_m else -90.0
            gb_roll = float(roll_m.group(1)) if roll_m else 0.0

            # Parse Camera Optics
            focal_m = self.FOCAL_LEN_PATTERN.search(text)
            dzoom_m = self.DZOOM_PATTERN.search(text)
            focal_len = float(focal_m.group(1)) if focal_m else 24.0
            dzoom_ratio = float(dzoom_m.group(1)) if dzoom_m else 1.0

            # Optional Exposure
            iso_m = self.ISO_PATTERN.search(text)
            iso = int(iso_m.group(1)) if iso_m else 100
            shutter_m = self.SHUTTER_PATTERN.search(text)
            shutter = shutter_m.group(1).strip() if shutter_m else "1/1000.0"
            fnum_m = self.FNUM_PATTERN.search(text)
            fnum = float(fnum_m.group(1)) if fnum_m else 2.8

            record = SRTTelemetryRecord(
                subtitle_index=sub_idx,
                frame_index=frame_idx,
                start_seconds=start_s,
                end_seconds=end_s,
                iso_timestamp=iso_time,
                latitude=lat,
                longitude=lon,
                rel_alt=rel_alt,
                abs_alt=abs_alt,
                gb_yaw=gb_yaw,
                gb_pitch=gb_pitch,
                gb_roll=gb_roll,
                focal_len=focal_len,
                dzoom_ratio=dzoom_ratio,
                iso=iso,
                shutter=shutter,
                fnum=fnum,
            )
            self.records.append(record)
            self._frame_to_record[frame_idx] = record
            self._timestamps.append(start_s)

        return len(self.records)

    def get_record_by_frame(self, frame_index: int) -> Optional[SRTTelemetryRecord]:
        """Returns exact or nearest telemetry record for a given frame index."""
        if not self.records:
            return None
        if 0 <= frame_index < len(self.records):
            return self.records[frame_index]
        
        # Clamp to available range
        idx = max(0, min(len(self.records) - 1, frame_index))
        return self.records[idx]

    def get_record_by_timestamp(self, timestamp_seconds: float) -> Optional[SRTTelemetryRecord]:
        """Binary search lookup for closest telemetry record by video timestamp."""
        if not self.records:
            return None
        
        import bisect
        pos = bisect.bisect_left(self._timestamps, timestamp_seconds)
        if pos == 0:
            return self.records[0]
        if pos >= len(self.records):
            return self.records[-1]
        
        before = self.records[pos - 1]
        after = self.records[pos]
        if abs(before.start_seconds - timestamp_seconds) <= abs(after.start_seconds - timestamp_seconds):
            return before
        return after

    def compute_ground_sampling_distance(
        self,
        image_width: int,
        image_height: int,
        record: Optional[SRTTelemetryRecord] = None,
        frame_index: int = 0,
    ) -> float:
        """
        Computes Ground Sampling Distance (GSD) in meters/pixel at image center.
        For a 35mm equivalent sensor (width 36.0mm):
          GSD = (Altitude * SensorWidth) / (FocalLength * ImageWidth)
        """
        rec = record or self.get_record_by_frame(frame_index)
        if not rec:
            return 0.05  # Standard 5cm/px fallback

        alt_m = max(5.0, rec.rel_alt)
        focal_mm = max(5.0, rec.focal_len * max(0.1, rec.dzoom_ratio))
        sensor_width_mm = 36.0  # 35mm full-frame reference

        # In nadir view:
        gsd_nadir = (alt_m * sensor_width_mm) / (focal_mm * max(1, image_width))

        # In oblique view with pitch theta (-90 is nadir, -18.5 is shallow forward):
        pitch_rad = math.radians(abs(rec.gb_pitch))
        # Distance along camera line of sight to ground center: D = H / sin(pitch)
        sin_pitch = max(0.15, math.sin(pitch_rad))
        line_of_sight_dist = alt_m / sin_pitch
        gsd_oblique = (line_of_sight_dist * sensor_width_mm) / (focal_mm * max(1, image_width))

        return float(round(gsd_oblique, 5))

    def pixel_to_ground_meters(
        self,
        u: float,
        v: float,
        image_width: int,
        image_height: int,
        record: Optional[SRTTelemetryRecord] = None,
        frame_index: int = 0,
    ) -> Tuple[float, float]:
        """
        Projects an image pixel (u, v) onto the real-world metric ground plane (X_meters, Y_meters)
        relative to the drone's ground nadir (0, 0).
        Uses exact 3D pinhole camera ray-plane intersection with gimbal pitch and yaw.
        """
        rec = record or self.get_record_by_frame(frame_index)
        if not rec:
            # Fallback linear scaling
            return (u - image_width / 2.0) * 0.05, (v - image_height / 2.0) * 0.05

        H = max(2.0, rec.rel_alt)
        f_35 = max(5.0, rec.focal_len * max(0.1, rec.dzoom_ratio))

        # Camera intrinsic matrix parameters (35mm sensor: 36mm x 20.25mm for 16:9)
        fx = (image_width * f_35) / 36.0
        fy = fx  # Square pixel assumption
        cx = image_width / 2.0
        cy = image_height / 2.0

        # Normalized ray in camera frame (X right, Y down, Z forward along optical axis)
        x_c = (u - cx) / fx
        y_c = (v - cy) / fy
        z_c = 1.0
        v_c = np.array([x_c, y_c, z_c], dtype=np.float64)
        v_c = v_c / np.linalg.norm(v_c)

        # Rotation from camera frame to world frame
        # Pitch theta: 0 is horizontal, -90 is nadir straight down
        pitch_rad = math.radians(rec.gb_pitch)
        roll_rad = math.radians(rec.gb_roll)
        yaw_rad = math.radians(rec.gb_yaw)

        # Pitch rotation (around camera X-axis)
        # Camera optical axis tilts downward by (90 + pitch) from horizontal
        # For pitch = -90 (nadir), optical axis points directly down (-Z_world)
        # For pitch = -18.5, optical axis is 18.5 deg below horizontal
        R_pitch = np.array([
            [1.0, 0.0, 0.0],
            [0.0, math.cos(pitch_rad), -math.sin(pitch_rad)],
            [0.0, math.sin(pitch_rad), math.cos(pitch_rad)],
        ], dtype=np.float64)

        # Roll rotation (around optical axis)
        R_roll = np.array([
            [math.cos(roll_rad), -math.sin(roll_rad), 0.0],
            [math.sin(roll_rad), math.cos(roll_rad), 0.0],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)

        # Yaw rotation (around world vertical Z axis)
        R_yaw = np.array([
            [math.cos(yaw_rad), -math.sin(yaw_rad), 0.0],
            [math.sin(yaw_rad), math.cos(yaw_rad), 0.0],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)

        # Combined camera to world rotation
        # Mapping: Camera Z is forward/down, Camera X is right (East-aligned before yaw), Camera Y is down-sensor
        R_c2w = R_yaw @ R_pitch @ R_roll

        # World ray direction
        v_w = R_c2w @ v_c

        # Ground intersection: Drone position is at (0, 0, H). Ground is at Z = 0.
        # Line: P(s) = [0, 0, H] + s * [v_w_x, v_w_y, v_w_z]
        # At ground Z = 0: H + s * v_w_z = 0 -> s = -H / v_w_z
        # Note: v_w_z must be negative (pointing toward ground)
        if abs(v_w[2]) < 1e-4:
            # Ray is nearly horizontal (horizon), clamp to far plane
            s = H / 0.1
        else:
            s = -H / v_w[2]

        if s < 0:
            # Ray points away from ground (skyward), clamp
            s = H / 0.1

        # Metric ground coordinates relative to drone ground nadir
        x_ground_m = float(s * v_w[0])
        y_ground_m = float(s * v_w[1])

        return x_ground_m, y_ground_m

    def generate_homography_matrix(
        self,
        image_width: int,
        image_height: int,
        record: Optional[SRTTelemetryRecord] = None,
        frame_index: int = 0,
    ) -> np.ndarray:
        """
        Computes a 3x3 perspective homography matrix H mapping image pixels [u, v, 1]^T
        to metric ground coordinates [X, Y, 1]^T in meters using 4 representative image points.
        """
        import cv2

        w, h = float(image_width), float(image_height)

        # 4 well-distributed image points (avoiding extreme horizon edges)
        src_points = np.array([
            [w * 0.20, h * 0.30],   # Top-Left
            [w * 0.80, h * 0.30],   # Top-Right
            [w * 0.80, h * 0.85],   # Bottom-Right
            [w * 0.20, h * 0.85],   # Bottom-Left
        ], dtype=np.float32)

        dst_points = []
        for pt in src_points:
            gx, gy = self.pixel_to_ground_meters(
                pt[0], pt[1], image_width, image_height, record=record, frame_index=frame_index
            )
            dst_points.append([gx, gy])

        dst_points = np.array(dst_points, dtype=np.float32)

        H = cv2.getPerspectiveTransform(src_points, dst_points)
        return H
