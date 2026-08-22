"""
Unit Tests for Level 2 Fine-Grained Vehicle & VRU Classifier
"""

import pytest
from backend.perception.classification.fine_grained import (
    FineGrainedClassifier,
    FineGrainedClass,
    FineGrainedClassification,
)


def test_fine_grained_classification_rules():
    classifier = FineGrainedClassifier(stabilization_frames=5)

    # 1. Pedestrian direct mapping
    res = classifier.classify_track(1, "person", 0.88, [100, 100, 130, 180])
    assert res.fine_class == FineGrainedClass.PEDESTRIAN

    # 2. Auto Rickshaw mapping
    res = classifier.classify_track(2, "awning-tricycle", 0.85, [200, 200, 260, 280])
    assert res.fine_class == FineGrainedClass.AUTO_RICKSHAW

    # 3. Two-wheeler Scooter vs Motorcycle
    res_scooter = classifier.classify_track(3, "motor", 0.80, [100, 100, 130, 135])
    assert res_scooter.fine_class in (FineGrainedClass.SCOOTER, FineGrainedClass.MOTORCYCLE)

    # 4. Bus detection
    res_bus = classifier.classify_track(4, "bus", 0.92, [100, 100, 250, 400])
    assert res_bus.fine_class == FineGrainedClass.BUS

    # 5. Heavy Truck
    res_hgv = classifier.classify_track(5, "truck", 0.90, [100, 100, 300, 450])
    assert res_hgv.fine_class in (FineGrainedClass.HEAVY_TRUCK, FineGrainedClass.TRUCK)


def test_fine_grained_caching_and_temporal_smoothing():
    classifier = FineGrainedClassifier(stabilization_frames=4)
    track_id = 99

    # Frame 1 to 3: Stabilizing (not cached yet)
    for f in range(3):
        res = classifier.classify_track(track_id, "car", 0.85, [100, 100, 220, 290])
        assert not res.is_cached

    # Frame 4: Locks cache
    res4 = classifier.classify_track(track_id, "car", 0.85, [100, 100, 220, 290])
    assert res4.is_cached
    assert track_id in classifier._track_cache

    # Subsequent frame: returns locked cached decision
    res5 = classifier.classify_track(track_id, "truck", 0.50, [100, 100, 220, 290])
    assert res5.is_cached
    assert res5.fine_class == res4.fine_class
