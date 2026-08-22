"""
Unit Tests for Road-User Taxonomy Normalization & Uncertainty
"""

import pytest
from backend.perception.classification.taxonomy import (
    RoadUserClass,
    normalize_class,
    CLASS_PALETTE,
)


def test_taxonomy_standard_classes():
    # Person
    res = normalize_class("person", 0.95)
    assert res.normalized_class == RoadUserClass.PERSON
    assert not res.is_uncertain

    # Motorcycle
    res = normalize_class("motorcycle", 0.88)
    assert res.normalized_class == RoadUserClass.MOTORCYCLE
    assert not res.is_uncertain

    # Car
    res = normalize_class("car", 0.92)
    assert res.normalized_class == RoadUserClass.CAR
    assert not res.is_uncertain

    # Bus
    res = normalize_class("bus", 0.85)
    assert res.normalized_class == RoadUserClass.BUS
    assert not res.is_uncertain


def test_taxonomy_uncertainty_handling():
    # Generic "truck" without explicit size should be marked uncertain
    res = normalize_class("truck", 0.75)
    assert res.normalized_class == RoadUserClass.HGV
    assert res.is_uncertain is True

    # Generic "vehicle" should be marked uncertain
    res = normalize_class("vehicle", 0.60)
    assert res.normalized_class == RoadUserClass.OTHER_VEHICLE
    assert res.is_uncertain is True

    # Explicit "heavy truck" should not be uncertain
    res = normalize_class("heavy truck", 0.85)
    assert res.normalized_class == RoadUserClass.HGV
    assert res.is_uncertain is False

    # Explicit "van" should map to LGV and not be uncertain
    res = normalize_class("van", 0.90)
    assert res.normalized_class == RoadUserClass.LGV
    assert res.is_uncertain is False


def test_taxonomy_palette_completeness():
    for cls in RoadUserClass:
        assert cls in CLASS_PALETTE
        hex_code, bgr = CLASS_PALETTE[cls]
        assert hex_code.startswith("#")
        assert len(bgr) == 3
