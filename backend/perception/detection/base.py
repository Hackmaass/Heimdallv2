"""
Base Detector Interface & Detection Data Structures
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple, Any
import numpy as np


@dataclass
class DetectedObject:
    """Raw bounding box detection from object detector."""
    class_id: int
    raw_class_name: str
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2]
    centroid: Tuple[float, float]
    track_id: Optional[int] = None
    embedding: Optional[np.ndarray] = None


@dataclass
class DetectionResult:
    """Batch/Frame detection result."""
    frame_index: int
    timestamp: float
    objects: List[DetectedObject]
    inference_time_ms: float
    raw_result: Any = None


class BaseDetector(ABC):
    """Abstract base class for all detection backends."""

    def __init__(
        self,
        model_name_or_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.50,
        img_size: int = 640,
        device: str = "auto",
    ):
        self.model_name_or_path = model_name_or_path
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.img_size = img_size
        self.device = self._resolve_device(device)

    @staticmethod
    def _resolve_device(device: str) -> str:
        """Determines best compute backend: CUDA, MPS (Apple Metal), or CPU."""
        if device != "auto":
            return device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    @abstractmethod
    def detect(self, frame: np.ndarray, frame_index: int = 0, timestamp: float = 0.0) -> DetectionResult:
        """Runs detection inference on a BGR image frame."""
        pass

    @abstractmethod
    def set_prompts(self, prompts: List[str]) -> None:
        """Sets custom class prompt list for open-vocabulary models."""
        pass
