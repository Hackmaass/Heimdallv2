"""
Spatial Exporter Module (Level 4 Spatial Grounding)
Exports grounded vehicle trajectories and road network analytics as GeoJSON, Spatial CSV, and JSON.
"""

import io
import csv
import json
from typing import List, Dict, Any, Optional

from .level4_engine import GroundedTrajectory


class SpatialExporter:
    """Provides streaming export generators for GeoJSON and Georeferenced CSV formats."""

    @staticmethod
    def to_geojson_string(level4_payload: Dict[str, Any], indent: int = 2) -> str:
        """Serializes Level 4 GeoJSON feature collection to string."""
        geojson = level4_payload.get("geojson", {"type": "FeatureCollection", "features": []})
        return json.dumps(geojson, indent=indent)

    @staticmethod
    def to_spatial_csv_string(grounded_trajectories: List[Dict[str, Any]]) -> str:
        """Serializes grounded vehicle trajectories into standard georeferenced CSV format."""
        output = io.StringIO()
        fieldnames = [
            "track_id",
            "vehicle_class",
            "confidence",
            "is_active",
            "latitude",
            "longitude",
            "road_segment",
            "approach",
            "lane",
            "direction",
            "distance_along_segment_m",
            "velocity_kmh",
            "acceleration_mps2",
            "heading_deg",
            "queue_state",
            "spatial_confidence",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for t in grounded_trajectories:
            writer.writerow({
                "track_id": t.get("track_id"),
                "vehicle_class": t.get("class"),
                "confidence": t.get("confidence"),
                "is_active": t.get("is_active"),
                "latitude": t.get("latitude"),
                "longitude": t.get("longitude"),
                "road_segment": t.get("road_segment"),
                "approach": t.get("approach"),
                "lane": t.get("lane"),
                "direction": t.get("direction"),
                "distance_along_segment_m": t.get("distance_along_segment_m"),
                "velocity_kmh": t.get("speed_kmh"),
                "acceleration_mps2": t.get("acceleration_mps2"),
                "heading_deg": t.get("heading_deg"),
                "queue_state": t.get("queue_state"),
                "spatial_confidence": t.get("spatial_confidence"),
            })

        return output.getvalue()
