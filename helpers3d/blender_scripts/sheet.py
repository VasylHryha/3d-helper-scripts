"""Put images side by side in one picture, in the order given."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
parser.add_argument("--columns", type=int, default=4)
parser.add_argument("--cell", type=int, default=512)
parser.add_argument("--images", nargs="+", required=True)
args = parser.parse_args(c.script_args())

c.empty_scene()
out = os.path.abspath(args.out)
os.makedirs(os.path.dirname(out), exist_ok=True)
c.compose_sheet([os.path.abspath(p) for p in args.images], out, args.columns, args.cell)
print("sheet: " + out)
