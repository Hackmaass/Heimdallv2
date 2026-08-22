"""
WebSocket Connection Manager for Real-Time Tracking Streams
"""

import asyncio
import json
import base64
from typing import List, Dict, Any, Optional
from fastapi import WebSocket
import cv2
import numpy as np


class ConnectionManager:
    """
    Manages active WebSocket subscribers to /ws/tracking.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast_json(self, message: Dict[str, Any]) -> None:
        """Broadcasts structured tracking updates to all connected frontends."""
        if not self.active_connections:
            return

        text = json.dumps(message)
        dead_sockets = []

        for connection in list(self.active_connections):
            try:
                await connection.send_text(text)
            except Exception:
                dead_sockets.append(connection)

        if dead_sockets:
            async with self._lock:
                for s in dead_sockets:
                    if s in self.active_connections:
                        self.active_connections.remove(s)

    async def broadcast_frame(self, payload: Dict[str, Any], frame_bgr: Optional[np.ndarray] = None) -> None:
        """Broadcasts payload with optional base64 JPEG frame."""
        if not self.active_connections:
            return

        msg = dict(payload)
        if frame_bgr is not None:
            # Resize slightly for smooth network streaming
            h, w = frame_bgr.shape[:2]
            scale = 960.0 / max(w, 1)
            if scale < 1.0:
                stream_frame = cv2.resize(frame_bgr, (int(w * scale), int(h * scale)))
            else:
                stream_frame = frame_bgr

            ret, buf = cv2.imencode(".jpg", stream_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ret:
                msg["image_b64"] = base64.b64encode(buf).decode("utf-8")

        await self.broadcast_json(msg)
