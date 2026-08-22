"""
Heimdallv2 Level 4 Spatial Grounding Module
Provides:
- Telemetry Ray-to-Ground Georeferencer (Image -> Ground Meters -> WGS-84 GPS)
- Georeferenced Road Network Topology (Intersections, Corridors, Approaches, Lanes)
- Map Matching Engine (Directional Continuity & Linear Stationing)
- Level 4 Spatial Aggregate Analytics Engine (Desire Lines, Per-Lane Metrics, Spatial Queues, Speed Map)
- GeoJSON & Spatial CSV Exporters
"""

from .georeferencer import SpatialGeoreferencer, GeoreferencedPoint, SpatialConfidenceFlag
from .road_network import RoadNetwork, RoadSegment, Lane, IntersectionNode, create_default_intersection_network
from .map_matcher import MapMatcher, MapMatchResult
from .level4_engine import Level4SpatialEngine, GroundedTrajectory, SpatialQueueExtent, GeographicDesireLine, LaneSpatialMetric
from .storage_exporter import SpatialExporter

__all__ = [
    "SpatialGeoreferencer",
    "GeoreferencedPoint",
    "SpatialConfidenceFlag",
    "RoadNetwork",
    "RoadSegment",
    "Lane",
    "IntersectionNode",
    "create_default_intersection_network",
    "MapMatcher",
    "MapMatchResult",
    "Level4SpatialEngine",
    "GroundedTrajectory",
    "SpatialQueueExtent",
    "GeographicDesireLine",
    "LaneSpatialMetric",
    "SpatialExporter",
]
