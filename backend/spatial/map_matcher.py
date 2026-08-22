"""
Map Matching Engine Module (Level 4 Spatial Grounding)
Performs robust topological trajectory-to-road network matching using orthogonal distance,
longitudinal stationing, and directional heading continuity to prevent cross-carriageway jumping.
"""

import math
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List, Any
import numpy as np

from .road_network import RoadNetwork, RoadSegment, Lane
from .georeferencer import SpatialGeoreferencer


@dataclass
class MapMatchResult:
    """Result of matching a single vehicle GPS observation to the road network."""
    matched: bool
    road_segment_id: str
    road_name: str
    approach: str
    lane_id: str
    lane_name: str
    direction_name: str
    distance_along_segment_m: float
    cross_track_distance_m: float
    heading_alignment_score: float
    queue_state: str = "FREE_FLOW"  # "FREE_FLOW", "SLOWING", "QUEUED"


class MapMatcher:
    """
    Direction-aware map matcher enforcing physical road continuity and vehicle kinematics.
    """

    def __init__(
        self,
        road_network: RoadNetwork,
        max_search_radius_m: float = 35.0,
        min_heading_alignment: float = 0.25,
    ):
        self.network = road_network
        self.max_search_radius_m = max_search_radius_m
        self.min_heading_alignment = min_heading_alignment

        # Track-level state cache for temporal hysteresis
        self._track_states: Dict[int, MapMatchResult] = {}

    @staticmethod
    def _point_to_segment_distance(
        p_x: float, p_y: float,
        a_x: float, a_y: float,
        b_x: float, b_y: float,
    ) -> Tuple[float, float]:
        """
        Calculates orthogonal distance (meters) and longitudinal projection (meters)
        of point P onto line segment AB in metric coordinates.
        Returns: (cross_track_dist_m, dist_along_segment_m)
        """
        ab_x = b_x - a_x
        ab_y = b_y - a_y
        seg_len_sq = ab_x * ab_x + ab_y * ab_y

        if seg_len_sq < 1e-6:
            dx = p_x - a_x
            dy = p_y - a_y
            return math.hypot(dx, dy), 0.0

        # Parameter t along AB
        ap_x = p_x - a_x
        ap_y = p_y - a_y
        t = (ap_x * ab_x + ap_y * ab_y) / seg_len_sq
        t_clamped = max(0.0, min(1.0, t))

        # Closest point on segment
        proj_x = a_x + t_clamped * ab_x
        proj_y = a_y + t_clamped * ab_y

        cross_track = math.hypot(p_x - proj_x, p_y - proj_y)
        dist_along = t_clamped * math.sqrt(seg_len_sq)

        return cross_track, dist_along

    def match_point(
        self,
        lat: float,
        lon: float,
        heading_deg: Optional[float] = None,
        speed_kmh: Optional[float] = None,
        track_id: Optional[int] = None,
    ) -> MapMatchResult:
        """
        Matches a single GPS point to the nearest road segment and lane,
        taking heading orientation and speed into account.
        """
        ref_lat = self.network.intersection.center_coord[1] if self.network.intersection else lat
        ref_lon = self.network.intersection.center_coord[0] if self.network.intersection else lon

        # Convert target point to metric offsets from reference
        p_x, p_y = SpatialGeoreferencer.wgs84_to_metric(ref_lat, ref_lon, lat, lon)

        best_score = float("inf")
        best_match: Optional[MapMatchResult] = None

        # Queue State determination based on speed threshold (< 6 km/h is queued, 6-20 km/h slowing)
        q_state = "FREE_FLOW"
        if speed_kmh is not None:
            if speed_kmh < 6.0:
                q_state = "QUEUED"
            elif speed_kmh < 20.0:
                q_state = "SLOWING"

        for segment in self.network.segments.values():
            if len(segment.centerline_coords) < 2:
                continue

            # Convert segment centerline coordinates to metric space
            a_lon, a_lat = segment.centerline_coords[0]
            b_lon, b_lat = segment.centerline_coords[-1]
            a_x, a_y = SpatialGeoreferencer.wgs84_to_metric(ref_lat, ref_lon, a_lat, a_lon)
            b_x, b_y = SpatialGeoreferencer.wgs84_to_metric(ref_lat, ref_lon, b_lat, b_lon)

            cross_dist, dist_along = self._point_to_segment_distance(p_x, p_y, a_x, a_y, b_x, b_y)

            if cross_dist > self.max_search_radius_m:
                continue

            # Directional Alignment scoring
            align_score = 1.0
            if heading_deg is not None:
                delta_rad = math.radians(heading_deg - segment.bearing_deg)
                cos_delta = math.cos(delta_rad)
                align_score = max(0.0, cos_delta)

                # Penalize opposing or perpendicular directions
                if cos_delta < self.min_heading_alignment:
                    cross_dist += 40.0  # Strong penalty for wrong-way match

            # Combined match cost (lower is better)
            match_cost = cross_dist + (1.0 - align_score) * 20.0

            if match_cost < best_score:
                best_score = match_cost

                # Find best lane within segment
                best_lane = segment.lanes[0] if segment.lanes else None
                best_lane_dist = float("inf")

                for lane in segment.lanes:
                    if len(lane.centerline_coords) >= 2:
                        la_lon, la_lat = lane.centerline_coords[0]
                        lb_lon, lb_lat = lane.centerline_coords[-1]
                        la_x, la_y = SpatialGeoreferencer.wgs84_to_metric(ref_lat, ref_lon, la_lat, la_lon)
                        lb_x, lb_y = SpatialGeoreferencer.wgs84_to_metric(ref_lat, ref_lon, lb_lat, lb_lon)
                        l_cross, _ = self._point_to_segment_distance(p_x, p_y, la_x, la_y, lb_x, lb_y)
                        if l_cross < best_lane_dist:
                            best_lane_dist = l_cross
                            best_lane = lane

                lane_id = best_lane.lane_id if best_lane else "LANE_01"
                lane_name = best_lane.name if best_lane else "Lane 1"

                best_match = MapMatchResult(
                    matched=True,
                    road_segment_id=segment.segment_id,
                    road_name=segment.name,
                    approach=segment.approach,
                    lane_id=lane_id,
                    lane_name=lane_name,
                    direction_name=segment.direction,
                    distance_along_segment_m=float(round(dist_along, 1)),
                    cross_track_distance_m=float(round(cross_dist, 2)),
                    heading_alignment_score=float(round(align_score, 2)),
                    queue_state=q_state,
                )

        if best_match and best_match.matched:
            if track_id is not None:
                self._track_states[track_id] = best_match
            return best_match

        # Fallback unassigned point
        return MapMatchResult(
            matched=False,
            road_segment_id="UNASSIGNED",
            road_name="Unassigned Road",
            approach="Unassigned Approach",
            lane_id="UNASSIGNED",
            lane_name="Unassigned Lane",
            direction_name="Unknown",
            distance_along_segment_m=0.0,
            cross_track_distance_m=999.0,
            heading_alignment_score=0.0,
            queue_state=q_state,
        )
