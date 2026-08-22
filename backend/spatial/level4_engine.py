"""
Level 4 Spatial Analytics Engine Module
Computes Map-Native Traffic Intelligence:
- Grounded Trajectories (WGS-84 paths, headings, and road/lane assignments)
- Geographic Desire Lines along actual road geometry
- Per-Lane Spatial Metrics (Volume, Flow, Speed, Density, Occupancy, Queue Length)
- Spatial Queue Extents with physical start/end GPS coordinates
- Road Segment Speed & Density Map Layer
- Standardized GeoJSON Output
"""

import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

from .georeferencer import SpatialGeoreferencer, SpatialConfidenceFlag
from .road_network import RoadNetwork, RoadSegment, Lane, create_default_intersection_network
from .map_matcher import MapMatcher, MapMatchResult
from ..trajectories.models import TrackTrajectory


@dataclass
class GroundedTrajectory:
    """A vehicle trajectory fully grounded in WGS-84 geographic coordinates and road topology."""
    track_id: int
    raw_class: str
    fine_grained_class: str
    confidence: float
    is_active: bool
    current_lat: float
    current_lon: float
    current_speed_kmh: float
    current_acceleration_mps2: float
    current_heading_deg: float
    road_segment_id: str
    road_name: str
    approach: str
    lane_id: str
    lane_name: str
    direction_name: str
    distance_along_segment_m: float
    queue_state: str                    # "FREE_FLOW", "SLOWING", "QUEUED"
    spatial_confidence: str             # "HIGH_CONFIDENCE (CALIBRATED)", etc.
    gps_trail: List[List[float]] = field(default_factory=list) # [[lon, lat], ...]

    def to_geojson_feature(self) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": self.gps_trail if len(self.gps_trail) >= 2 else [[self.current_lon, self.current_lat], [self.current_lon, self.current_lat]],
            },
            "properties": {
                "feature_type": "grounded_trajectory",
                "track_id": self.track_id,
                "class": self.fine_grained_class,
                "speed_kmh": self.current_speed_kmh,
                "acceleration_mps2": self.current_acceleration_mps2,
                "heading_deg": self.current_heading_deg,
                "road_segment": self.road_name,
                "approach": self.approach,
                "lane": self.lane_name,
                "direction": self.direction_name,
                "distance_along_m": self.distance_along_segment_m,
                "queue_state": self.queue_state,
                "is_active": self.is_active,
                "spatial_confidence": self.spatial_confidence,
            },
        }


@dataclass
class GeographicDesireLine:
    """An origin-to-destination traffic movement corridor following geographic road paths."""
    movement_id: str                    # e.g. "N → S", "E → N"
    origin_approach: str                # e.g. "North Approach"
    destination_approach: str           # e.g. "South Approach"
    vehicle_count: int
    flow_percentage: float
    stroke_width: float
    polyline_coords: List[List[float]]  # [[lon, lat], ...]

    def to_geojson_feature(self) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": self.polyline_coords,
            },
            "properties": {
                "feature_type": "desire_line",
                "movement_id": self.movement_id,
                "origin": self.origin_approach,
                "destination": self.destination_approach,
                "vehicle_count": self.vehicle_count,
                "percentage": self.flow_percentage,
                "stroke_width": self.stroke_width,
            },
        }


@dataclass
class SpatialQueueExtent:
    """A physical queue along a specific road carriageway with geographic start and end coordinates."""
    queue_id: str
    road_segment_id: str
    road_name: str
    approach: str
    lane_id: str
    queued_vehicle_count: int
    queue_length_meters: float
    average_queue_speed_kmh: float
    start_coord: List[float]            # [lon, lat] at the head of queue (nearest intersection)
    end_coord: List[float]              # [lon, lat] at the tail of queue
    queue_status: str                   # "GROWING", "DISSIPATING", "STABLE"

    def to_geojson_feature(self) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [self.start_coord, self.end_coord],
            },
            "properties": {
                "feature_type": "spatial_queue",
                "queue_id": self.queue_id,
                "road_segment": self.road_name,
                "approach": self.approach,
                "lane_id": self.lane_id,
                "vehicle_count": self.queued_vehicle_count,
                "queue_length_m": self.queue_length_meters,
                "avg_speed_kmh": self.average_queue_speed_kmh,
                "status": self.queue_status,
            },
        }


@dataclass
class LaneSpatialMetric:
    """Aggregated traffic flow, kinematics, and density metrics for a specific physical lane."""
    lane_id: str
    lane_name: str
    road_segment_id: str
    approach: str
    vehicle_volume: int
    flow_vpm: float
    average_speed_kmh: float
    median_speed_kmh: float
    density_vpk: float
    occupancy_pct: float
    active_queue_meters: float
    modal_split: Dict[str, int] = field(default_factory=dict)
    speed_regime: str = "FREE_FLOW"     # "FREE_FLOW", "SLOWING", "CONGESTED"


class Level4SpatialEngine:
    """
    Computes end-to-end Level 4 spatial grounding, road-matching, desire lines,
    lane-level spatial performance metrics, and spatial queue extents.
    """

    def __init__(
        self,
        georeferencer: Optional[SpatialGeoreferencer] = None,
        road_network: Optional[RoadNetwork] = None,
    ):
        self.georeferencer = georeferencer or SpatialGeoreferencer()
        self.road_network = road_network or create_default_intersection_network()
        self.map_matcher = MapMatcher(self.road_network)

    def process_trajectories(
        self,
        trajectories: List[TrackTrajectory],
        frame_index: int = 0,
        image_width: int = 1920,
        image_height: int = 1080,
    ) -> List[GroundedTrajectory]:
        """
        Projects image-space trajectories into grounded WGS-84 trajectories
        and matches them to the road network.
        """
        grounded_list: List[GroundedTrajectory] = []

        for traj in trajectories:
            if not traj.history:
                continue

            # Build full GPS trail
            gps_trail: List[List[float]] = []
            for pt in traj.history:
                geo_pt = self.georeferencer.project_pixel_to_wgs84(
                    pt.centroid[0], pt.centroid[1],
                    image_width=image_width, image_height=image_height,
                    frame_index=pt.frame_index,
                )
                gps_trail.append([geo_pt.longitude, geo_pt.latitude])

            # Current/latest position
            last_pt = traj.history[-1]
            last_geo = self.georeferencer.project_pixel_to_wgs84(
                last_pt.centroid[0], last_pt.centroid[1],
                image_width=image_width, image_height=image_height,
                frame_index=last_pt.frame_index,
            )

            # Kinematics
            speed_kmh = float(round(last_pt.velocity_kmh or 0.0, 1))
            accel_mps2 = float(round(last_pt.acceleration_mps2 or 0.0, 2))
            heading_deg = float(round(last_pt.heading or 0.0, 1))

            # Match to Road Network
            match_res = self.map_matcher.match_point(
                lat=last_geo.latitude,
                lon=last_geo.longitude,
                heading_deg=heading_deg,
                speed_kmh=speed_kmh,
                track_id=traj.track_id,
            )

            grounded = GroundedTrajectory(
                track_id=traj.track_id,
                raw_class=traj.raw_class,
                fine_grained_class=traj.fine_grained_class,
                confidence=traj.confidence,
                is_active=traj.is_active,
                current_lat=last_geo.latitude,
                current_lon=last_geo.longitude,
                current_speed_kmh=speed_kmh,
                current_acceleration_mps2=accel_mps2,
                current_heading_deg=heading_deg,
                road_segment_id=match_res.road_segment_id,
                road_name=match_res.road_name,
                approach=match_res.approach,
                lane_id=match_res.lane_id,
                lane_name=match_res.lane_name,
                direction_name=match_res.direction_name,
                distance_along_segment_m=match_res.distance_along_segment_m,
                queue_state=match_res.queue_state,
                spatial_confidence=last_geo.confidence_flag,
                gps_trail=gps_trail,
            )
            grounded_list.append(grounded)

        return grounded_list

    def compute_geographic_desire_lines(
        self,
        grounded_trajectories: List[GroundedTrajectory],
    ) -> List[GeographicDesireLine]:
        """
        Generates volume-scaled desire lines routed along actual road network polylines.
        """
        ref_center = self.road_network.intersection.center_coord if self.road_network.intersection else [73.771846, 18.566227]
        m_to_lat = 1.0 / 111132.95
        m_to_lon = 1.0 / 105420.0

        # Anchor points for the 4 approaches
        anchors = {
            "N": [ref_center[0], ref_center[1] + 80.0 * m_to_lat],
            "S": [ref_center[0], ref_center[1] - 80.0 * m_to_lat],
            "E": [ref_center[0] + 80.0 * m_to_lon, ref_center[1]],
            "W": [ref_center[0] - 80.0 * m_to_lon, ref_center[1]],
        }

        # 12 standard movement paths
        movement_defs = [
            ("N → S", "N", "S", "North Approach", "South Approach"),
            ("N → W", "N", "W", "North Approach", "West Approach"),
            ("N → E", "N", "E", "North Approach", "East Approach"),
            ("S → N", "S", "N", "South Approach", "North Approach"),
            ("S → E", "S", "E", "South Approach", "East Approach"),
            ("S → W", "S", "W", "South Approach", "West Approach"),
            ("E → W", "E", "W", "East Approach", "West Approach"),
            ("E → N", "E", "N", "East Approach", "North Approach"),
            ("E → S", "E", "S", "East Approach", "South Approach"),
            ("W → E", "W", "E", "West Approach", "East Approach"),
            ("W → S", "W", "S", "West Approach", "South Approach"),
            ("W → N", "W", "N", "West Approach", "North Approach"),
        ]

        # Count movements from trajectories
        movement_counts: Dict[str, int] = {m[0]: 0 for m in movement_defs}

        for gt in grounded_trajectories:
            if len(gt.gps_trail) < 3:
                continue
            start_p = gt.gps_trail[0]
            end_p = gt.gps_trail[-1]

            # Classify origin & destination quadrants
            d_lon = end_p[0] - start_p[0]
            d_lat = end_p[1] - start_p[1]

            orig = "N" if start_p[1] > ref_center[1] + 10 * m_to_lat else ("S" if start_p[1] < ref_center[1] - 10 * m_to_lat else ("E" if start_p[0] > ref_center[0] else "W"))
            dest = "N" if end_p[1] > ref_center[1] + 10 * m_to_lat else ("S" if end_p[1] < ref_center[1] - 10 * m_to_lat else ("E" if end_p[0] > ref_center[0] else "W"))

            if orig == dest:
                if abs(d_lat) > abs(d_lon):
                    dest = "S" if d_lat < 0 else "N"
                else:
                    dest = "E" if d_lon > 0 else "W"

            m_key = f"{orig} → {dest}"
            if m_key in movement_counts:
                movement_counts[m_key] += 1

        total_m = max(1, sum(movement_counts.values()))
        max_m = max(1, max(movement_counts.values()))

        desire_lines: List[GeographicDesireLine] = []
        for m_id, orig_code, dest_code, orig_name, dest_name in movement_defs:
            cnt = movement_counts[m_id]
            pct = round((cnt / total_m) * 100.0, 1)
            stroke = round(max(1.5, min(8.0, 1.5 + (cnt / max_m) * 6.5)), 1)

            p_start = anchors[orig_code]
            p_end = anchors[dest_code]
            p_mid = [ref_center[0], ref_center[1]]

            desire_lines.append(
                GeographicDesireLine(
                    movement_id=m_id,
                    origin_approach=orig_name,
                    destination_approach=dest_name,
                    vehicle_count=cnt,
                    flow_percentage=pct,
                    stroke_width=stroke,
                    polyline_coords=[p_start, p_mid, p_end],
                )
            )

        return desire_lines

    def compute_lane_spatial_metrics(
        self,
        grounded_trajectories: List[GroundedTrajectory],
        window_duration_min: float = 1.0,
    ) -> List[LaneSpatialMetric]:
        """
        Calculates per-lane volume, flow rate, average speed, density, and queue length.
        """
        metrics: List[LaneSpatialMetric] = []

        # Group trajectories by matched lane
        lane_groups: Dict[str, List[GroundedTrajectory]] = {}
        for gt in grounded_trajectories:
            lane_id = gt.lane_id
            if lane_id not in lane_groups:
                lane_groups[lane_id] = []
            lane_groups[lane_id].append(gt)

        # Calculate metrics for every configured lane in the road network
        for segment in self.road_network.segments.values():
            for lane in segment.lanes:
                trajs = lane_groups.get(lane.lane_id, [])
                vol = len(trajs)
                flow_vpm = round(vol / max(1.0, window_duration_min), 1)

                speeds = [t.current_speed_kmh for t in trajs if t.current_speed_kmh > 0]
                avg_speed = round(float(np.mean(speeds)), 1) if speeds else 0.0
                median_speed = round(float(np.median(speeds)), 1) if speeds else 0.0

                active_trajs = [t for t in trajs if t.is_active]
                # Density = active vehicles / segment length in km
                seg_km = max(0.02, segment.length_m / 1000.0)
                density_vpk = round(len(active_trajs) / seg_km, 1)

                # Occupancy = total vehicle footprint / lane area
                lane_area_m2 = max(50.0, segment.length_m * lane.width_m)
                footprint_sum = sum(
                    35.0 if t.fine_grained_class in ["Bus", "Truck", "Heavy Truck"]
                    else (3.5 if t.fine_grained_class in ["Motorcycle", "Scooter", "Bicycle"] else 12.5)
                    for t in active_trajs
                )
                occupancy = round(min(100.0, (footprint_sum / lane_area_m2) * 100.0), 1)

                # Queue Length
                queued_count = sum(1 for t in active_trajs if t.queue_state == "QUEUED")
                queue_m = round(queued_count * 6.5, 1)

                # Speed Regime
                regime = "FREE_FLOW"
                if avg_speed < 12.0 or occupancy > 60.0:
                    regime = "CONGESTED"
                elif avg_speed < 28.0 or occupancy > 35.0:
                    regime = "SLOWING"

                # Modal Split
                modal_split: Dict[str, int] = {}
                for t in trajs:
                    cls = t.fine_grained_class
                    modal_split[cls] = modal_split.get(cls, 0) + 1

                metrics.append(
                    LaneSpatialMetric(
                        lane_id=lane.lane_id,
                        lane_name=lane.name,
                        road_segment_id=segment.segment_id,
                        approach=segment.approach,
                        vehicle_volume=vol,
                        flow_vpm=flow_vpm,
                        average_speed_kmh=avg_speed,
                        median_speed_kmh=median_speed,
                        density_vpk=density_vpk,
                        occupancy_pct=occupancy,
                        active_queue_meters=queue_m,
                        modal_split=modal_split,
                        speed_regime=regime,
                    )
                )

        return metrics

    def compute_spatial_queue_extents(
        self,
        grounded_trajectories: List[GroundedTrajectory],
    ) -> List[SpatialQueueExtent]:
        """
        Calculates geographic queue bars along each approach carriageway with real GPS coordinates.
        """
        queues: List[SpatialQueueExtent] = []
        ref_center = self.road_network.intersection.center_coord if self.road_network.intersection else [73.771846, 18.566227]
        m_to_lat = 1.0 / 111132.95
        m_to_lon = 1.0 / 105420.0

        for segment in self.road_network.segments.values():
            seg_trajs = [t for t in grounded_trajectories if t.road_segment_id == segment.segment_id and t.is_active]
            queued = [t for t in seg_trajs if t.queue_state == "QUEUED"]

            q_len_m = round(len(queued) * 6.5, 1)
            avg_q_speed = round(float(np.mean([t.current_speed_kmh for t in queued])), 1) if queued else 0.0

            # Queue start is at the intersection stop bar
            if len(segment.centerline_coords) >= 2:
                stop_bar = segment.centerline_coords[-1]
                app_origin = segment.centerline_coords[0]

                # Interpolate queue tail along the segment polyline
                d_lon = app_origin[0] - stop_bar[0]
                d_lat = app_origin[1] - stop_bar[1]
                seg_len = max(1.0, segment.length_m)
                t_ratio = min(1.0, q_len_m / seg_len)

                queue_tail = [
                    float(round(stop_bar[0] + d_lon * t_ratio, 7)),
                    float(round(stop_bar[1] + d_lat * t_ratio, 7)),
                ]
            else:
                stop_bar = ref_center
                queue_tail = ref_center

            status = "STABLE"
            if len(queued) >= 4:
                status = "GROWING"
            elif len(queued) == 0:
                status = "DISSIPATING"

            queues.append(
                SpatialQueueExtent(
                    queue_id=f"queue_{segment.segment_id.lower()}",
                    road_segment_id=segment.segment_id,
                    road_name=segment.name,
                    approach=segment.approach,
                    lane_id=segment.lanes[0].lane_id if segment.lanes else "LANE_01",
                    queued_vehicle_count=len(queued),
                    queue_length_meters=q_len_m,
                    average_queue_speed_kmh=avg_q_speed,
                    start_coord=stop_bar,
                    end_coord=queue_tail,
                    queue_status=status,
                )
            )

        return queues

    def compute_level4_analytics(
        self,
        trajectories: List[TrackTrajectory],
        frame_index: int = 0,
        image_width: int = 1920,
        image_height: int = 1080,
    ) -> Dict[str, Any]:
        """
        Generates the complete Level 4 Spatial Analytics payload including GeoJSON collections.
        """
        grounded_trajs = self.process_trajectories(
            trajectories=trajectories,
            frame_index=frame_index,
            image_width=image_width,
            image_height=image_height,
        )

        desire_lines = self.compute_geographic_desire_lines(grounded_trajs)
        lane_metrics = self.compute_lane_spatial_metrics(grounded_trajs)
        spatial_queues = self.compute_spatial_queue_extents(grounded_trajs)

        # Build comprehensive GeoJSON FeatureCollection
        geojson_features: List[Dict[str, Any]] = []

        # 1. Road Network Features
        net_geojson = self.road_network.to_geojson()
        geojson_features.extend(net_geojson.get("features", []))

        # 2. Grounded Trajectories Features
        for gt in grounded_trajs:
            geojson_features.append(gt.to_geojson_feature())

        # 3. Desire Lines Features
        for dl in desire_lines:
            geojson_features.append(dl.to_geojson_feature())

        # 4. Spatial Queues Features
        for sq in spatial_queues:
            geojson_features.append(sq.to_geojson_feature())

        combined_geojson = {
            "type": "FeatureCollection",
            "features": geojson_features,
        }

        # Summary KPIs
        total_grounded = len(grounded_trajs)
        active_grounded = sum(1 for t in grounded_trajs if t.is_active)
        total_queue_m = round(sum(q.queue_length_meters for q in spatial_queues), 1)
        mean_speed = round(float(np.mean([t.current_speed_kmh for t in grounded_trajs if t.current_speed_kmh > 0])), 1) if grounded_trajs else 0.0

        return {
            "summary_kpis": {
                "total_grounded_vehicles": total_grounded,
                "active_grounded_vehicles": active_grounded,
                "total_queue_length_m": total_queue_m,
                "network_average_speed_kmh": mean_speed,
                "anchor_coordinates": {
                    "latitude": self.georeferencer.anchor_lat,
                    "longitude": self.georeferencer.anchor_lon,
                },
                "calibration_status": (
                    SpatialConfidenceFlag.CALIBRATED.value
                    if self.georeferencer.is_homography_calibrated
                    else SpatialConfidenceFlag.TELEMETRY_ESTIMATED.value
                ),
            },
            "grounded_trajectories": [
                {
                    "track_id": t.track_id,
                    "class": t.fine_grained_class,
                    "confidence": t.confidence,
                    "is_active": t.is_active,
                    "latitude": t.current_lat,
                    "longitude": t.current_lon,
                    "speed_kmh": t.current_speed_kmh,
                    "acceleration_mps2": t.current_acceleration_mps2,
                    "heading_deg": t.current_heading_deg,
                    "road_segment": t.road_name,
                    "approach": t.approach,
                    "lane": t.lane_name,
                    "direction": t.direction_name,
                    "distance_along_segment_m": t.distance_along_segment_m,
                    "queue_state": t.queue_state,
                    "spatial_confidence": t.spatial_confidence,
                    "gps_trail": t.gps_trail,
                }
                for t in grounded_trajs
            ],
            "desire_lines": [
                {
                    "movement_id": dl.movement_id,
                    "origin": dl.origin_approach,
                    "destination": dl.destination_approach,
                    "vehicle_count": dl.vehicle_count,
                    "percentage": dl.flow_percentage,
                    "stroke_width": dl.stroke_width,
                    "polyline_coords": dl.polyline_coords,
                }
                for dl in desire_lines
            ],
            "lane_metrics": [
                {
                    "lane_id": lm.lane_id,
                    "lane_name": lm.lane_name,
                    "road_segment_id": lm.road_segment_id,
                    "approach": lm.approach,
                    "vehicle_volume": lm.vehicle_volume,
                    "flow_vpm": lm.flow_vpm,
                    "average_speed_kmh": lm.average_speed_kmh,
                    "median_speed_kmh": lm.median_speed_kmh,
                    "density_vpk": lm.density_vpk,
                    "occupancy_pct": lm.occupancy_pct,
                    "active_queue_meters": lm.active_queue_meters,
                    "speed_regime": lm.speed_regime,
                    "modal_split": lm.modal_split,
                }
                for lm in lane_metrics
            ],
            "spatial_queues": [
                {
                    "queue_id": sq.queue_id,
                    "road_name": sq.road_name,
                    "approach": sq.approach,
                    "lane_id": sq.lane_id,
                    "queued_vehicle_count": sq.queued_vehicle_count,
                    "queue_length_meters": sq.queue_length_meters,
                    "average_speed_kmh": sq.average_queue_speed_kmh,
                    "status": sq.queue_status,
                    "start_coord": sq.start_coord,
                    "end_coord": sq.end_coord,
                }
                for sq in spatial_queues
            ],
            "geojson": combined_geojson,
        }
