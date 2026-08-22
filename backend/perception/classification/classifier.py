"""
Classification Layer Module
"""

from typing import List, Optional
from .taxonomy import NormalizedClassification, normalize_class, RoadUserClass


class ClassificationLayer:
    """
    Standardized classification interface allowing plug-and-play swapping of
    open-vocab, fine-tuned, or ensemble secondary classifiers.
    """

    def __init__(self, custom_mapping: Optional[dict] = None):
        self.custom_mapping = custom_mapping or {}

    def classify(
        self,
        raw_class_name: str,
        confidence: float,
        bbox: Optional[List[float]] = None,
    ) -> NormalizedClassification:
        return normalize_class(raw_class_name, confidence, bbox)


__all__ = ["ClassificationLayer", "NormalizedClassification", "RoadUserClass", "normalize_class"]
