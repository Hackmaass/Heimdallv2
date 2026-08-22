"""
Road Network Topology Module (Level 4 Spatial Grounding)
Defines topological road infrastructure models (Intersections, Road Segments, Lanes, Approaches, Queue Zones)
and generates standardized GeoJSON FeatureCollections for map-native rendering.
"""

import math
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple


@dataclass
class Lane:
    """Individual physical traffic lane with spatial geometry and permitted movements."""
    lane_id: str
    lane_index: int
    name: str
    width_m: float
    centerline_coords: List[List[float]]  # [[lon, lat], [lon, lat], ...]
    permitted_movements: List[str] = field(default_factory=list)  # e.g. ["N → S", "N → W"]
    speed_limit_kmh: float = 50.0

    def to_geojson_feature(self, segment_id: str) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": self.centerline_coords,
            },
            "properties": {
                "feature_type": "lane",
                "lane_id": self.lane_id,
                "lane_index": self.lane_index,
                "name": self.name,
                "segment_id": segment_id,
                "width_m": self.width_m,
                "permitted_movements": self.permitted_movements,
                "speed_limit_kmh": self.speed_limit_kmh,
            },
        }


@dataclass
class RoadSegment:
    """A directional carriageway corridor or approach link."""
    segment_id: str
    name: str
    approach: str                     # "North Approach", "South Approach", "East Approach", "West Approach"
    direction: str                    # "Northbound", "Southbound", "Eastbound", "Westbound"
    bearing_deg: float                # Nominal azimuth heading [0, 360)
    length_m: float
    centerline_coords: List[List[float]]  # [[lon, lat], ...]
    lanes: List[Lane] = field(default_factory=list)
    speed_limit_kmh: float = 50.0

    def to_geojson_feature(self) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": self.centerline_coords,
            },
            "properties": {
                "feature_type": "road_segment",
                "segment_id": self.segment_id,
                "name": self.name,
                "approach": self.approach,
                "direction": self.direction,
                "bearing_deg": self.bearing_deg,
                "length_m": self.length_m,
                "lane_count": len(self.lanes),
                "speed_limit_kmh": self.speed_limit_kmh,
            },
        }


@dataclass
class IntersectionNode:
    """Central traffic junction node."""
    intersection_id: str
    name: str
    center_coord: List[float]         # [lon, lat]
    boundary_polygon: List[List[float]] # [[lon, lat], [lon, lat], ...]
    diameter_m: float = 40.0

    def to_geojson_feature(self) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [self.boundary_polygon],
            },
            "properties": {
                "feature_type": "intersection",
                "intersection_id": self.intersection_id,
                "name": self.name,
                "center": self.center_coord,
                "diameter_m": self.diameter_m,
            },
        }


class RoadNetwork:
    """
    Topological container for geographic road infrastructure.
    Provides fast spatial distance queries and GeoJSON export.
    """

    def __init__(
        self,
        intersection: Optional[IntersectionNode] = None,
        segments: Optional[List[RoadSegment]] = None,
    ):
        self.intersection = intersection
        self.segments: Dict[str, RoadSegment] = {s.segment_id: s for s in (segments or [])}
        self.lanes: Dict[str, Tuple[RoadSegment, Lane]] = {}
        for s in self.segments.values():
            for l in s.lanes:
                self.lanes[l.lane_id] = (s, l)

    def add_segment(self, segment: RoadSegment) -> None:
        self.segments[segment.segment_id] = segment
        for l in segment.lanes:
            self.lanes[l.lane_id] = (segment, l)

    def get_segment(self, segment_id: str) -> Optional[RoadSegment]:
        return self.segments.get(segment_id)

    def get_lane(self, lane_id: str) -> Optional[Tuple[RoadSegment, Lane]]:
        return self.lanes.get(lane_id)

    def to_geojson(self) -> Dict[str, Any]:
        """Exports entire road network as a valid GeoJSON FeatureCollection."""
        features = []
        if self.intersection:
            features.append(self.intersection.to_geojson_feature())

        for segment in self.segments.values():
            features.append(segment.to_geojson_feature())
            for lane in segment.lanes:
                features.append(lane.to_geojson_feature(segment.segment_id))

        return {
            "type": "FeatureCollection",
            "features": features,
        }


def create_default_intersection_network(
    center_lat: float = 18.566227,
    center_lon: float = 73.771846,
) -> RoadNetwork:
    """
    Constructs a calibrated 4-arm intersection road network model
    georeferenced around the drone surveillance coordinates.
    """
    # Offset helpers in meters -> degrees (~111.13km / deg lat, ~105.4km / deg lon at 18.5 deg)
    m_to_lat = 1.0 / 111132.95
    m_to_lon = 1.0 / 105420.0

    # 1. Intersection Junction Node
    r_m = 22.0
    poly = [
        [center_lon - r_m * m_to_lon, center_lat + r_m * m_to_lat], # NW
        [center_lon + r_m * m_to_lon, center_lat + r_m * m_to_lat], # NE
        [center_lon + r_m * m_to_lon, center_lat - r_m * m_to_lat], # SE
        [center_lon - r_m * m_to_lon, center_lat - r_m * m_to_lat], # SW
        [center_lon - r_m * m_to_lon, center_lat + r_m * m_to_lat], # Close
    ]
    intersection = IntersectionNode(
        intersection_id="INT_01",
        name="Hinjawadi Commercial Crossing",
        center_coord=[center_lon, center_lat],
        boundary_polygon=poly,
        diameter_m=44.0,
    )

    # Arm Length = 90 meters
    arm_len = 90.0
    lane_w = 3.5

    # ── 2. North Approach Corridor (Heading South toward intersection: bearing 180°) ──
    # Starts at +arm_len North, terminates at +r_m North
    n_start_lat = center_lat + arm_len * m_to_lat
    n_end_lat = center_lat + r_m * m_to_lat

    seg_north_in = RoadSegment(
        segment_id="SEG_NORTH_IN",
        name="Northbound Approach (Inbound)",
        approach="North Approach",
        direction="Southbound (Inbound)",
        bearing_deg=180.0,
        length_m=arm_len - r_m,
        centerline_coords=[
            [center_lon - 3.5 * m_to_lon, n_start_lat],
            [center_lon - 3.5 * m_to_lon, n_end_lat],
        ],
        lanes=[
            Lane(
                lane_id="LANE_01_N_THRU",
                lane_index=1,
                name="North Approach Lane 1 (Through / Right)",
                width_m=lane_w,
                centerline_coords=[
                    [center_lon - 5.25 * m_to_lon, n_start_lat],
                    [center_lon - 5.25 * m_to_lon, n_end_lat],
                ],
                permitted_movements=["N → S", "N → W"],
            ),
            Lane(
                lane_id="LANE_02_N_LEFT",
                lane_index=2,
                name="North Approach Lane 2 (Through / Left)",
                width_m=lane_w,
                centerline_coords=[
                    [center_lon - 1.75 * m_to_lon, n_start_lat],
                    [center_lon - 1.75 * m_to_lon, n_end_lat],
                ],
                permitted_movements=["N → S", "N → E"],
            ),
        ],
    )

    # ── 3. South Approach Corridor (Heading North toward intersection: bearing 0°) ────
    s_start_lat = center_lat - arm_len * m_to_lat
    s_end_lat = center_lat - r_m * m_to_lat

    seg_south_in = RoadSegment(
        segment_id="SEG_SOUTH_IN",
        name="Southbound Approach (Inbound)",
        approach="South Approach",
        direction="Northbound (Inbound)",
        bearing_deg=0.0,
        length_m=arm_len - r_m,
        centerline_coords=[
            [center_lon + 3.5 * m_to_lon, s_start_lat],
            [center_lon + 3.5 * m_to_lon, s_end_lat],
        ],
        lanes=[
            Lane(
                lane_id="LANE_03_S_THRU",
                lane_index=1,
                name="South Approach Lane 1 (Through / Right)",
                width_m=lane_w,
                centerline_coords=[
                    [center_lon + 5.25 * m_to_lon, s_start_lat],
                    [center_lon + 5.25 * m_to_lon, s_end_lat],
                ],
                permitted_movements=["S → N", "S → E"],
            ),
            Lane(
                lane_id="LANE_04_S_LEFT",
                lane_index=2,
                name="South Approach Lane 2 (Through / Left)",
                width_m=lane_w,
                centerline_coords=[
                    [center_lon + 1.75 * m_to_lon, s_start_lat],
                    [center_lon + 1.75 * m_to_lon, s_end_lat],
                ],
                permitted_movements=["S → N", "S → W"],
            ),
        ],
    )

    # ── 4. East Approach Corridor (Heading West toward intersection: bearing 270°) ────
    e_start_lon = center_lon + arm_len * m_to_lon
    e_end_lon = center_lon + r_m * m_to_lon

    seg_east_in = RoadSegment(
        segment_id="SEG_EAST_IN",
        name="Eastbound Approach (Inbound)",
        approach="East Approach",
        direction="Westbound (Inbound)",
        bearing_deg=270.0,
        length_m=arm_len - r_m,
        centerline_coords=[
            [e_start_lon, center_lat + 3.5 * m_to_lat],
            [e_end_lon, center_lat + 3.5 * m_to_lat],
        ],
        lanes=[
            Lane(
                lane_id="LANE_05_E_THRU",
                lane_index=1,
                name="East Approach Lane 1 (Through / Right)",
                width_m=lane_w,
                centerline_coords=[
                    [e_start_lon, center_lat + 5.25 * m_to_lat],
                    [e_end_lon, center_lat + 5.25 * m_to_lat],
                ],
                permitted_movements=["E → W", "E → N"],
            ),
            Lane(
                lane_id="LANE_06_E_LEFT",
                lane_index=2,
                name="East Approach Lane 2 (Through / Left)",
                width_m=lane_w,
                centerline_coords=[
                    [e_start_lon, center_lat + 1.75 * m_to_lat],
                    [e_end_lon, center_lat + 1.75 * m_to_lat],
                ],
                permitted_movements=["E → W", "E → S"],
            ),
        ],
    )

    # ── 5. West Approach Corridor (Heading East toward intersection: bearing 90°) ─────
    w_start_lon = center_lon - arm_len * m_to_lon
    w_end_lon = center_lon - r_m * m_to_lon

    seg_west_in = RoadSegment(
        segment_id="SEG_WEST_IN",
        name="Westbound Approach (Inbound)",
        approach="West Approach",
        direction="Eastbound (Inbound)",
        bearing_deg=90.0,
        length_m=arm_len - r_m,
        centerline_coords=[
            [w_start_lon, center_lat - 3.5 * m_to_lat],
            [w_end_lon, center_lat - 3.5 * m_to_lat],
        ],
        lanes=[
            Lane(
                lane_id="LANE_07_W_THRU",
                lane_index=1,
                name="West Approach Lane 1 (Through / Right)",
                width_m=lane_w,
                centerline_coords=[
                    [w_start_lon, center_lat - 5.25 * m_to_lat],
                    [w_end_lon, center_lat - 5.25 * m_to_lat],
                ],
                permitted_movements=["W → E", "W → S"],
            ),
            Lane(
                lane_id="LANE_08_W_LEFT",
                lane_index=2,
                name="West Approach Lane 2 (Through / Left)",
                width_m=lane_w,
                centerline_coords=[
                    [w_start_lon, center_lat - 1.75 * m_to_lat],
                    [w_end_lon, center_lat - 1.75 * m_to_lat],
                ],
                permitted_movements=["W → E", "W → N"],
            ),
        ],
    )

    return RoadNetwork(
        intersection=intersection,
        segments=[seg_north_in, seg_south_in, seg_east_in, seg_west_in],
    )
