"""
CLI Runner for Heimdallv2 Perception Pipeline
Example:
    python -m scripts.run_pipeline --video data/sample.mp4 --tracker botsort --conf 0.25
"""

import argparse
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.pipeline import HeimdallPipeline
from backend.ingestion.file_source import FileSource


def main():
    parser = argparse.ArgumentParser(description="Heimdallv2 Aerial Perception Pipeline Runner")
    parser.add_argument("--video", type=str, required=True, help="Path to input video file")
    parser.add_argument("--tracker", type=str, default="botsort", choices=["botsort", "bytetrack"], help="MOT algorithm")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="YOLO model path or identifier")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--output", type=str, default="outputs", help="Output directory")
    parser.add_argument("--frame-skip", type=int, default=1, help="Process every N frames")
    parser.add_argument("--max-frames", type=int, default=None, help="Maximum number of frames to process")
    parser.add_argument("--no-video", action="store_true", help="Skip rendering annotated MP4")

    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"Error: Input video not found at: {args.video}")
        sys.exit(1)

    print(f"=================================================================")
    print(f"  HEIMDALLv2 CV PIPELINE RUNNER")
    print(f"  Input Video: {args.video}")
    print(f"  Tracker:     {args.tracker.upper()}")
    print(f"  Model:       {args.model}")
    print(f"  Conf Thresh: {args.conf}")
    print(f"  Output Dir:  {args.output}")
    if args.max_frames:
        print(f"  Max Frames:  {args.max_frames}")
    print(f"=================================================================")

    pipeline = HeimdallPipeline(
        tracker_type=args.tracker,
        model_path=args.model,
        confidence_threshold=args.conf,
        output_dir=args.output,
        process_every_n_frames=args.frame_skip,
        save_annotated_video=not args.no_video,
    )

    source = FileSource(file_path=args.video)
    video_id = os.path.splitext(os.path.basename(args.video))[0]

    status = pipeline.process_video(video_source=source, video_id=video_id, max_frames=args.max_frames)

    if status.status == "COMPLETED":
        print("\nPipeline Processing Successfully Completed!")
        print(f"Total Unique Tracks: {status.total_unique_tracks}")
        print("Generated Output Artifacts:")
        for k, v in status.output_files.items():
            print(f"  - {k}: {v}")
    else:
        print(f"\nPipeline Failed: {status.error_message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
