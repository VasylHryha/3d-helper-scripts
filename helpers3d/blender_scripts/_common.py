"""Shared helpers for the scripts in this folder. Runs inside Blender: `blender -b --python <script> -- <args>`."""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

VIEWS = {
    # Camera side, looking at the model. The model faces -Y (the glTF/Tripo convention), so "left" is the
    # model's left side: the camera sits on +X.
    "front": (0, -1, 0),
    "left": (1, 0, 0),
    "back": (0, 1, 0),
    "right": (-1, 0, 0),
    "top": (0, -0.001, 1),
    "three_quarter": (0.7, -0.7, 0.45),
}


def script_args():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=path)
        else:
            bpy.ops.import_scene.obj(filepath=path)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        raise SystemExit("Unsupported model type: " + ext)


def mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def world_bounds(objects):
    low = Vector((math.inf,) * 3)
    high = Vector((-math.inf,) * 3)
    for obj in objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            low = Vector(map(min, low, point))
            high = Vector(map(max, high, point))
    return low, high


def setup_render(size, transparent=True):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"  # no GPU needed, same result on every platform
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.film_transparent = transparent
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE"
    shading.show_object_outline = False
    scene.display.render_aa = "8"
    return scene


def framing(objects):
    low, high = world_bounds(objects)
    center = (low + high) / 2
    radius = max((high - low).length / 2, 1e-6)
    return center, radius


def add_camera(radius):
    """Returns the camera and the distance that keeps a sphere of this radius in frame."""
    data = bpy.data.cameras.new("h3d_camera")
    data.lens, data.sensor_width = 50, 36
    camera = bpy.data.objects.new("h3d_camera", data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    half_fov = math.atan(data.sensor_width / 2 / data.lens)
    return camera, radius / math.sin(half_fov) * 1.1


def aim(camera, center, direction, distance):
    direction = Vector(direction).normalized()
    camera.location = center + direction * distance
    camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def compose_sheet(paths, out_path, columns, cell, background=(0.2, 0.2, 0.2)):
    """Fits each image in a square cell on a grey background. Pixels are passed through untouched (Non-Color)."""
    rows = (len(paths) + columns - 1) // columns
    sheet = np.empty((rows * cell, columns * cell, 3), dtype=np.float32)
    sheet[:] = background
    for index, path in enumerate(paths):
        image = bpy.data.images.load(path)
        image.colorspace_settings.name = "Non-Color"
        width, height = image.size
        fit = min(cell / width, cell / height)
        if fit != 1:
            image.scale(max(1, int(width * fit)), max(1, int(height * fit)))
            width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        pixels = pixels.reshape(height, width, 4)[::-1]  # Blender stores rows bottom-up
        alpha = pixels[:, :, 3:4]
        top = (index // columns) * cell + (cell - height) // 2
        left = (index % columns) * cell + (cell - width) // 2
        region = sheet[top:top + height, left:left + width]
        sheet[top:top + height, left:left + width] = pixels[:, :, :3] * alpha + region * (1 - alpha)
    canvas = bpy.data.images.new("h3d_sheet", columns * cell, rows * cell, alpha=False)
    canvas.colorspace_settings.name = "Non-Color"
    rgba = np.ones((rows * cell, columns * cell, 4), dtype=np.float32)
    rgba[:, :, :3] = sheet[::-1]
    canvas.pixels.foreach_set(rgba.ravel())
    canvas.filepath_raw = out_path
    canvas.file_format = "PNG"
    canvas.save()
