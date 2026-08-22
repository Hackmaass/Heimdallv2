"""
Normalized Road-User Taxonomy & Uncertainty Resolution Layer
"""

from enum import Enum
from typing import NamedTuple, Optional, Dict, Tuple


class RoadUserClass(str, Enum):
    PERSON = "PERSON"
    BICYCLE = "BICYCLE"
    MOTORCYCLE = "MOTORCYCLE"
    CAR = "CAR"
    LGV = "LGV"              # Light Goods Vehicle (Van, Pickup Truck, Small Delivery)
    HGV = "HGV"              # Heavy Goods Vehicle (Large Multi-Axle, Container, Tipper)
    BUS = "BUS"              # Transit & Tour Busses
    OTHER_VEHICLE = "OTHER_VEHICLE"  # Auto Rickshaw, Tractor, Emergency, Unclassified


class NormalizedClassification(NamedTuple):
    normalized_class: RoadUserClass
    raw_class: str
    confidence: float
    is_uncertain: bool
    color_hex: str
    color_bgr: Tuple[int, int, int]


# Aviation & Drone Tactical Display Colors (Clean, high-contrast, professional palette)
CLASS_PALETTE: Dict[RoadUserClass, Tuple[str, Tuple[int, int, int]]] = {
    RoadUserClass.PERSON:        ("#00FFB2", (178, 255, 0)),    # Bright Cyan-Green
    RoadUserClass.BICYCLE:       ("#00E5FF", (255, 229, 0)),    # Vivid Cyan
    RoadUserClass.MOTORCYCLE:    ("#C8F23A", (58, 242, 200)),   # Volt Lime
    RoadUserClass.CAR:           ("#38BDF8", (248, 189, 56)),   # Sky Blue
    RoadUserClass.LGV:           ("#FB923C", (60, 146, 251)),   # Bright Amber-Orange
    RoadUserClass.HGV:           ("#F43F5E", (94, 63, 244)),    # Rose Crimson
    RoadUserClass.BUS:           ("#A855F7", (247, 85, 168)),   # Vivid Purple
    RoadUserClass.OTHER_VEHICLE: ("#E2E8F0", (240, 232, 226)),  # Titanium Silver
}


# Direct mapping dictionary from raw detector outputs
RAW_MAPPING: Dict[str, Tuple[RoadUserClass, bool]] = {
    # Person / Pedestrian
    "person": (RoadUserClass.PERSON, False),
    "pedestrian": (RoadUserClass.PERSON, False),
    "human": (RoadUserClass.PERSON, False),
    "person_2": (RoadUserClass.PERSON, False),

    # Bicycle
    "bicycle": (RoadUserClass.BICYCLE, False),
    "bike": (RoadUserClass.BICYCLE, False),
    "cyclist": (RoadUserClass.BICYCLE, False),

    # Motorcycle / Scooter
    "motorcycle": (RoadUserClass.MOTORCYCLE, False),
    "motorbike": (RoadUserClass.MOTORCYCLE, False),
    "scooter": (RoadUserClass.MOTORCYCLE, False),
    "moped": (RoadUserClass.MOTORCYCLE, False),
    "two-wheeler": (RoadUserClass.MOTORCYCLE, False),
    "twowheeler": (RoadUserClass.MOTORCYCLE, False),

    # Passenger Car / Light Vehicle
    "car": (RoadUserClass.CAR, False),
    "sedan": (RoadUserClass.CAR, False),
    "suv": (RoadUserClass.CAR, False),
    "hatchback": (RoadUserClass.CAR, False),
    "jeep": (RoadUserClass.CAR, False),
    "cab": (RoadUserClass.CAR, False),
    "taxi": (RoadUserClass.CAR, False),

    # Light Goods Vehicle (LGV)
    "van": (RoadUserClass.LGV, False),
    "pickup": (RoadUserClass.LGV, False),
    "pickup truck": (RoadUserClass.LGV, False),
    "pickuptruck": (RoadUserClass.LGV, False),
    "minivan": (RoadUserClass.LGV, False),
    "delivery van": (RoadUserClass.LGV, False),
    "light truck": (RoadUserClass.LGV, False),

    # Heavy Goods Vehicle (HGV)
    "heavy truck": (RoadUserClass.HGV, False),
    "semi truck": (RoadUserClass.HGV, False),
    "lorry": (RoadUserClass.HGV, False),
    "container": (RoadUserClass.HGV, False),
    "trailer": (RoadUserClass.HGV, False),
    "tipper": (RoadUserClass.HGV, False),

    # Generic "truck" - uncertain whether LGV or HGV unless specified by bbox size/model
    "truck": (RoadUserClass.HGV, True),

    # Bus
    "bus": (RoadUserClass.BUS, False),
    "minibus": (RoadUserClass.BUS, False),
    "coach": (RoadUserClass.BUS, False),

    # Other / Specialized Urban Vehicles
    "auto": (RoadUserClass.OTHER_VEHICLE, False),
    "auto rickshaw": (RoadUserClass.OTHER_VEHICLE, False),
    "autorickshaw": (RoadUserClass.OTHER_VEHICLE, False),
    "rikshaw": (RoadUserClass.OTHER_VEHICLE, False),
    "rickshaw": (RoadUserClass.OTHER_VEHICLE, False),
    "tuk-tuk": (RoadUserClass.OTHER_VEHICLE, False),
    "tuktuk": (RoadUserClass.OTHER_VEHICLE, False),
    "cart": (RoadUserClass.OTHER_VEHICLE, False),
    "carts": (RoadUserClass.OTHER_VEHICLE, False),
    "tractor": (RoadUserClass.OTHER_VEHICLE, False),
    "emergency vehicle": (RoadUserClass.OTHER_VEHICLE, False),
    "ambulance": (RoadUserClass.OTHER_VEHICLE, False),
    "fire truck": (RoadUserClass.OTHER_VEHICLE, False),
    "police": (RoadUserClass.OTHER_VEHICLE, False),
    "vehicle": (RoadUserClass.OTHER_VEHICLE, True),
}


def normalize_class(
    raw_class_name: str,
    confidence: float,
    bbox: Optional[list] = None,
) -> NormalizedClassification:
    """
    Normalizes arbitrary detector class names into standardized RoadUserClass taxonomy.
    Preserves raw class label and flags uncertain classifications (e.g. generic truck/vehicle).
    """
    raw_clean = str(raw_class_name).strip().lower()

    if raw_clean in RAW_MAPPING:
        road_class, uncertain = RAW_MAPPING[raw_clean]
    else:
        road_class = RoadUserClass.OTHER_VEHICLE
        uncertain = True
        for key, (mapped_cls, is_unc) in RAW_MAPPING.items():
            if key in raw_clean:
                road_class = mapped_cls
                uncertain = is_unc
                break

    if raw_clean == "truck" and bbox is not None and len(bbox) == 4:
        w = max(1.0, float(bbox[2] - bbox[0]))
        h = max(1.0, float(bbox[3] - bbox[1]))
        area = w * h
        if area < 5000:
            road_class = RoadUserClass.LGV
            uncertain = True
        else:
            road_class = RoadUserClass.HGV
            uncertain = True

    hex_color, bgr_color = CLASS_PALETTE.get(
        road_class, ("#E2E8F0", (240, 232, 226))
    )

    return NormalizedClassification(
        normalized_class=road_class,
        raw_class=raw_class_name,
        confidence=float(confidence),
        is_uncertain=uncertain,
        color_hex=hex_color,
        color_bgr=bgr_color,
    )
