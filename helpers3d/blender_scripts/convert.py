"""Convert between glb/gltf/fbx/obj/blend.

--height scales uniformly to that height. --ground centres on the origin and rests on z=0.
"""
import argparse
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--height", type=float)
parser.add_argument("--ground", action="store_true")
args = parser.parse_args(c.script_args())

c.empty_scene()
c.import_model(os.path.abspath(args.model))
roots = [o for o in bpy.context.scene.objects if o.parent is None]
meshes = c.mesh_objects()
if args.height and meshes:
    low, high = c.world_bounds(meshes)
    factor = args.height / max(high.z - low.z, 1e-9)
    for obj in roots:
        obj.scale = obj.scale * factor
        obj.location = obj.location * factor
    bpy.context.view_layer.update()
if args.ground and meshes:
    low, high = c.world_bounds(meshes)
    for obj in roots:
        obj.location.x -= (low.x + high.x) / 2
        obj.location.y -= (low.y + high.y) / 2
        obj.location.z -= low.z
    bpy.context.view_layer.update()

out = os.path.abspath(args.out)
os.makedirs(os.path.dirname(out), exist_ok=True)
ext = os.path.splitext(out)[1].lower()
if ext in (".glb", ".gltf"):
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE")
elif ext == ".fbx":
    bpy.ops.export_scene.fbx(filepath=out)
elif ext == ".obj":
    if hasattr(bpy.ops.wm, "obj_export"):
        bpy.ops.wm.obj_export(filepath=out)
    else:
        bpy.ops.export_scene.obj(filepath=out)
elif ext == ".blend":
    bpy.ops.wm.save_as_mainfile(filepath=out)
else:
    raise SystemExit("Unsupported output type: " + ext)
print("convert: wrote " + out)
