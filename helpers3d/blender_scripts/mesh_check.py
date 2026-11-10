"""Report on a model: triangles, size, UVs, textures, loose parts and open edges.

Writes JSON. With --strict, exits 2 when there are warnings.
"""
import argparse
import json
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--json", required=True)
parser.add_argument("--max-tris", type=int)
parser.add_argument("--strict", action="store_true")
args = parser.parse_args(c.script_args())

c.empty_scene()
c.import_model(os.path.abspath(args.model))
objects = c.mesh_objects()
depsgraph = bpy.context.evaluated_depsgraph_get()
triangles = loose = open_edges = 0
without_uv = []
for obj in objects:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    triangles += sum(len(p.vertices) - 2 for p in mesh.polygons)
    if not mesh.uv_layers:
        without_uv.append(obj.name)
    builder = bmesh.new()
    builder.from_mesh(mesh)
    open_edges += sum(1 for e in builder.edges if len(e.link_faces) != 2)
    seen = set()
    for vert in builder.verts:
        if vert.index in seen:
            continue
        loose += 1
        stack = [vert]
        while stack:
            current = stack.pop()
            if current.index in seen:
                continue
            seen.add(current.index)
            stack.extend(e.other_vert(current) for e in current.link_edges)
    builder.free()
    evaluated.to_mesh_clear()

size = [0, 0, 0]
if objects:
    low, high = c.world_bounds(objects)
    size = [round(v, 4) for v in (high - low)]
report = {
    "model": os.path.basename(args.model),
    "mesh_objects": len(objects),
    "triangles": triangles,
    "size_xyz": size,
    "materials": len(bpy.data.materials),
    "textures": sorted({"%s %dx%d" % (i.name, i.size[0], i.size[1]) for i in bpy.data.images if i.size[0]}),
    "objects_without_uv": without_uv,
    "loose_parts": loose,
    "open_edges": open_edges,
    "armatures": sum(1 for o in bpy.context.scene.objects if o.type == "ARMATURE"),
    "actions": len(bpy.data.actions),
}
warnings = []
if not objects:
    warnings.append("no mesh found")
if without_uv:
    warnings.append("objects without UVs: " + ", ".join(without_uv))
if loose > len(objects):
    warnings.append("%d loose parts across %d objects" % (loose, len(objects)))
if open_edges:
    warnings.append("%d open or non-manifold edges" % open_edges)
if args.max_tris and triangles > args.max_tris:
    warnings.append("%d triangles is over the limit %d" % (triangles, args.max_tris))
report["warnings"] = warnings
out = os.path.abspath(args.json)
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2)
print(json.dumps(report, indent=2))
if args.strict and warnings:
    sys.exit(2)
