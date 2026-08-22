import sys
import os

# Ensure Heimdallv2 root is in python path for test discovery
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
