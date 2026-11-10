"""Render frames of a model turning around its centre: turn_000.png, turn_001.png, ..."""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--frames", type=int, default=24)
parser.add_argument("--size", type=int, default=512)
args = parser.parse_args(c.script_args())

c.empty_scene()
c.import_model(os.path.abspath(args.model))
c.setup_render(args.size)
center, radius = c.framing(c.mesh_objects())
camera, distance = c.add_camera(radius)
out = os.path.abspath(args.out)
os.makedirs(out, exist_ok=True)
for frame in range(args.frames):
    angle = 2 * math.pi * frame / args.frames
    c.aim(camera, center, (math.sin(angle) * 0.9, -math.cos(angle) * 0.9, 0.35), distance)
    c.render_to(os.path.join(out, "turn_%03d.png" % frame))
print("turntable: %d frames in %s" % (args.frames, out))
