"""
Heimdallv2 Second-Stage Fine-Grained Vehicle & Vulnerable Road User Classifier
Categorizes detected and tracked road users into 13 fine-grained classes:
  - Car, SUV, Sedan, Hatchback, Van, Bus, Truck, Heavy Truck, Auto Rickshaw,
    Motorcycle, Scooter, Bicycle, Pedestrian.

Features:
  1. Geometry & aspect-ratio inference combined with detector priors.
  2. Temporal smoothing: Accumulates confidence across early track observations.
  3. Track-level decision caching: Once locked, prevents frame-to-frame flickering.
  4. Pluggable / modular interface.
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple, NamedTuple
import math


class FineGrainedClass(str, Enum):
    PEDESTRIAN = "Pedestrian"
    BICYCLE = "Bicycle"
    MOTORCYCLE = "Motorcycle"
    SCOOTER = "Scooter"
    AUTO_RICKSHAW = "Auto Rickshaw"
    SEDAN = "Sedan"
    HATCHBACK = "Hatchback"
    SUV = "SUV"
    CAR = "Car"
    VAN = "Van"
    BUS = "Bus"
    TRUCK = "Truck"
    HEAVY_TRUCK = "Heavy Truck"


class FineGrainedClassification(NamedTuple):
    fine_class: FineGrainedClass
    confidence: float
    is_cached: bool
    evidence: str


# Aviation / Tactical Color Palette for Fine-Grained Classes
FINE_PALETTE: Dict[FineGrainedClass, Tuple[str, Tuple[int, int, int]]] = {
    FineGrainedClass.PEDESTRIAN:    ("#00FFB2", (178, 255, 0)),
    FineGrainedClass.BICYCLE:       ("#00E5FF", (255, 229, 0)),
    FineGrainedClass.MOTORCYCLE:    ("#C8F23A", (58, 242, 200)),
    FineGrainedClass.SCOOTER:       ("#A3E635", (53, 230, 163)),
    FineGrainedClass.AUTO_RICKSHAW: ("#FACC15", (21, 204, 250)),
    FineGrainedClass.SEDAN:         ("#38BDF8", (248, 189, 56)),
    FineGrainedClass.HATCHBACK:     ("#60A5FA", (250, 165, 96)),
    FineGrainedClass.SUV:           ("#818CF8", (248, 140, 129)),
    FineGrainedClass.CAR:           ("#38BDF8", (248, 189, 56)),
    FineGrainedClass.VAN:           ("#FB923C", (60, 146, 251)),
    FineGrainedClass.BUS:           ("#A855F7", (247, 85, 168)),
    FineGrainedClass.TRUCK:         ("#F43F5E", (94, 63, 244)),
    FineGrainedClass.HEAVY_TRUCK:   ("#E11D48", (72, 29, 225)),
}


class FineGrainedClassifier:
    """
    Second-Stage Classifier for Tracked Entities.
    Implements rule-based spatial-geometric analysis with temporal confidence voting.
    """

    def __init__(self, stabilization_frames: int = 6):
        self.stabilization_frames = stabilization_frames
        # Cache: track_id -> (locked_classification, observation_history)
        self._track_cache: Dict[int, FineGrainedClassification] = {}
        self._vote_history: Dict[int, List[Tuple[FineGrainedClass, float]]] = {}

    def classify_track(
        self,
        track_id: int,
        raw_class_name: str,
        detection_conf: float,
        bbox: List[float],
        speed_estimate: float = 0.0,
    ) -> FineGrainedClassification:
        """
        Classifies a tracked entity with temporal smoothing and decision caching.
        """
        # If track decision is already stabilized and cached, return cached result
        if track_id in self._track_cache:
            return self._track_cache[track_id]

        # Compute single-frame instantaneous candidate classification
        instant_class, instant_conf, evidence = self._classify_instance(
            raw_class_name=raw_class_name,
            conf=detection_conf,
            bbox=bbox,
            speed=speed_estimate,
        )

        # Accumulate vote history
        if track_id not in self._vote_history:
            self._vote_history[track_id] = []
        self._vote_history[track_id].append((instant_class, instant_conf))

        # Check if enough observations have been accumulated for stabilization
        history = self._vote_history[track_id]
        if len(history) >= self.stabilization_frames:
            # Weighted majority voting across observation window
            class_scores: Dict[FineGrainedClass, float] = {}
            for cls_vote, conf_vote in history:
                class_scores[cls_vote] = class_scores.get(cls_vote, 0.0) + conf_vote

            best_class = max(class_scores, key=class_scores.get) # type: ignore
            total_weight = sum(class_scores.values())
            stabilized_conf = class_scores[best_class] / max(0.001, total_weight)

            result = FineGrainedClassification(
                fine_class=best_class,
                confidence=round(stabilized_conf, 3),
                is_cached=True,
                evidence=f"Stabilized across {len(history)} frames (vote ratio: {stabilized_conf:.1%})",
            )
            self._track_cache[track_id] = result
            return result

        # Return instantaneous result while stabilizing
        return FineGrainedClassification(
            fine_class=instant_class,
            confidence=round(instant_conf, 3),
            is_cached=False,
            evidence=f"Stabilizing ({len(history)}/{self.stabilization_frames} frames): {evidence}",
        )

    def _classify_instance(
        self,
        raw_class_name: str,
        conf: float,
        bbox: List[float],
        speed: float,
    ) -> Tuple[FineGrainedClass, float, str]:
        """
        Infers fine-grained category from raw class detection + bounding box geometry.
        """
        raw = raw_class_name.strip().lower()
        w = max(1.0, float(bbox[2] - bbox[0]))
        h = max(1.0, float(bbox[3] - bbox[1]))
        area = w * h
        aspect_ratio = max(w / h, h / w)  # elongation ratio >= 1.0

        # ── 1. Pedestrian / Person ──────────────────────────────────────────
        if raw in ("person", "pedestrian", "people", "human"):
            return FineGrainedClass.PEDESTRIAN, conf, "Direct pedestrian detection"

        # ── 2. Bicycles ─────────────────────────────────────────────────────
        if raw in ("bicycle", "bike", "cyclist"):
            return FineGrainedClass.BICYCLE, conf, "Direct bicycle detection"

        # ── 3. Two-Wheelers (Motorcycle vs Scooter) ──────────────────────────
        if raw in ("motorcycle", "motor", "motorbike", "scooter", "moped", "two-wheeler"):
            # Scooters tend to be slightly more compact and have step-through geometry
            if area < 1600 or aspect_ratio < 1.4:
                return FineGrainedClass.SCOOTER, conf * 0.92, f"Compact 2-wheeler geometry (area={int(area)})"
            return FineGrainedClass.MOTORCYCLE, conf, "Standard motorcycle detection"

        # ── 4. Auto-Rickshaws & Three-Wheelers ──────────────────────────────
        if raw in ("auto", "auto rickshaw", "autorickshaw", "rikshaw", "rickshaw", "tricycle", "awning-tricycle", "awning_tricycle", "tuk-tuk"):
            return FineGrainedClass.AUTO_RICKSHAW, conf, "3-wheeler / Rickshaw detection"

        # ── 5. Buses ────────────────────────────────────────────────────────
        if raw in ("bus", "minibus", "coach") or (raw in ("truck", "car") and area > 18000 and aspect_ratio > 2.2):
            return FineGrainedClass.BUS, conf, f"Large transit chassis (area={int(area)}, AR={aspect_ratio:.1f})"

        # ── 6. Heavy Goods vs Light Goods Trucks ────────────────────────────
        if raw in ("heavy truck", "semi truck", "lorry", "container", "trailer", "tipper") or (raw == "truck" and area > 14000):
            return FineGrainedClass.HEAVY_TRUCK, conf, f"Multi-axle heavy cargo chassis (area={int(area)})"

        if raw in ("truck", "light truck", "pickup", "pickup truck", "pickuptruck"):
            return FineGrainedClass.TRUCK, conf, f"Commercial truck chassis (area={int(area)})"

        # ── 7. Vans & Light Commercial Vehicles ─────────────────────────────
        if raw in ("van", "minivan", "delivery van"):
            return FineGrainedClass.VAN, conf, "Light commercial van detection"

        # ── 8. Passenger Cars (SUV vs Sedan vs Hatchback) ───────────────────
        if raw in ("car", "sedan", "suv", "hatchback", "jeep", "cab", "taxi", "vehicle"):
            # Geometric differentiation from aerial bounding box:
            # SUV: Larger square/broad footprint with high volume
            # Sedan: Elongated rectangular footprint (high aspect ratio)
            # Hatchback: Compact shorter rectangular footprint
            if area > 8500 or (area > 6500 and aspect_ratio < 1.45):
                return FineGrainedClass.SUV, conf * 0.90, f"Broad elevated vehicle footprint (area={int(area)}, AR={aspect_ratio:.2f})"
            elif aspect_ratio > 1.75:
                return FineGrainedClass.SEDAN, conf * 0.92, f"Elongated notchback footprint (area={int(area)}, AR={aspect_ratio:.2f})"
            elif area < 5000:
                return FineGrainedClass.HATCHBACK, conf * 0.90, f"Compact 2-box hatchback footprint (area={int(area)}, AR={aspect_ratio:.2f})"
            return FineGrainedClass.CAR, conf, "Standard passenger car"

        return FineGrainedClass.CAR, 0.70, f"Default vehicle normalization from '{raw}'"

    def clear(self) -> None:
        """Clears all cached track classifications."""
        self._track_cache.clear()
        self._vote_history.clear()
