"""
Synthetic Intersection Drone Video Generator for Testing
Generates a realistic 10-second 30fps 1280x720 video with multiple moving vehicles.
"""

import os
import cv2
import numpy as np
import math


def generate_synthetic_intersection_video(
    output_path: str = "data/synthetic_intersection.mp4",
    duration_sec: int = 5,
    fps: int = 30,
    width: int = 1280,
    height: int = 720,
):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    total_frames = duration_sec * fps

    # Vehicle definitions: [x, y, vx, vy, width, height, color_bgr, label]
    vehicles = [
        # Car traveling East
        {"x": 50, "y": 320, "vx": 4.5, "vy": 0.0, "w": 65, "h": 35, "color": (248, 189, 56), "label": "car"},
        # Bus traveling East
        {"x": 100, "y": 360, "vx": 3.0, "vy": 0.0, "w": 120, "h": 45, "color": (247, 85, 168), "label": "bus"},
        # Car traveling West
        {"x": 1200, "y": 420, "vx": -4.0, "vy": 0.0, "w": 65, "h": 35, "color": (248, 189, 56), "label": "car"},
        # Motorcycle traveling South
        {"x": 620, "y": 30, "vx": 0.0, "vy": 5.0, "w": 30, "h": 20, "color": (58, 242, 200), "label": "motorcycle"},
        # Pedestrian crossing South
        {"x": 540, "y": 180, "vx": 0.0, "vy": 1.2, "w": 18, "h": 18, "color": (178, 255, 0), "label": "person"},
    ]

    for f in range(total_frames):
        # Road Canvas (Dark Asphalt with Yellow & White Lane Markings)
        frame = np.full((height, width, 3), (35, 38, 42), dtype=np.uint8)

        # Horizontal Road
        cv2.rectangle(frame, (0, 280), (width, 480), (45, 48, 54), -1)
        # Vertical Road
        cv2.rectangle(frame, (520, 0), (760, height), (45, 48, 54), -1)

        # Center Dashed Lines (Horizontal)
        for x in range(0, width, 40):
            if x < 520 or x > 760:
                cv2.line(frame, (x, 380), (x + 20, 380), (0, 215, 255), 2)

        # Center Dashed Lines (Vertical)
        for y in range(0, height, 40):
            if y < 280 or y > 480:
                cv2.line(frame, (640, y), (640, y + 20), (255, 255, 255), 2)

        # Update and draw moving objects
        for v in vehicles:
            vx_curr = v["x"] + v["vx"] * f
            vy_curr = v["y"] + v["vy"] * f

            x1, y1 = int(vx_curr), int(vy_curr)
            x2, y2 = int(vx_curr + v["w"]), int(vy_curr + v["h"])

            # Body rectangle
            cv2.rectangle(frame, (x1, y1), (x2, y2), v["color"], -1)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 1)

        out.write(frame)

    out.release()
    print(f"Generated synthetic test video: {output_path} ({total_frames} frames)")


if __name__ == "__main__":
    generate_synthetic_intersection_video()
