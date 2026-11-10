"""Render front, left, back, right, top and three-quarter views plus views_sheet.png."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--size", type=int, default=512)
args = parser.parse_args(c.script_args())

c.empty_scene()
c.import_model(os.path.abspath(args.model))
c.setup_render(args.size)
center, radius = c.framing(c.mesh_objects())
camera, distance = c.add_camera(radius)
out = os.path.abspath(args.out)
os.makedirs(out, exist_ok=True)
paths = []
for name, direction in c.VIEWS.items():
    c.aim(camera, center, direction, distance)
    paths.append(os.path.join(out, name + ".png"))
    c.render_to(paths[-1])
c.compose_sheet(paths, os.path.join(out, "views_sheet.png"), 3, args.size)
print("views: wrote %d views and views_sheet.png in %s" % (len(paths), out))
