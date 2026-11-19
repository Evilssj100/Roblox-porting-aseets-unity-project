"""Render a ported stage in (cloud) Blender to check tile placement, walls and the scenario camera before
uploading anything: imports every tile FBX at its placement (Roblox space -> Blender: (x, y, z) -> (-x, z, y)),
draws walls (red) and triggers (green) as wire boxes and player spawns as markers, and renders from the
original brawler camera at the first player spawn.

Usage: python preview_stage.py <MissionData.json> <tiles_dir> <mission_id> <stage_number> <out.png> [--wide]
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

src, tiles_dir, mid, num, out = sys.argv[1:6]
wide = "--wide" in sys.argv
data = json.load(open(src))
stage = next(s for s in data["Missions"][mid]["stages"] if s["number"] == int(num))
B = np.array([[-1.0, 0, 0], [0, 0, 1], [0, 1, 0]])


def to_blender(cfv, scale=1.0):
    p = np.array(cfv[:3])
    R = np.array(cfv[3:]).reshape(3, 3)
    m = np.eye(4)
    m[:3, :3] = B @ R @ B * scale
    m[:3, 3] = B @ p
    return Matrix(m.tolist())


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
for t in stage["tiles"]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=f"{tiles_dir}/{t['tile']}.fbx", axis_forward="-Z", axis_up="Y")
    M = to_blender(t["cf"], t["scale"])
    for o in set(bpy.data.objects) - before:
        if o.parent is None:
            o.matrix_world = M @ o.matrix_world


def wire_box(b, color):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.active_object
    o.matrix_world = to_blender(b["cf"]) @ Matrix.Diagonal((*[b["size"][i] for i in (0, 2, 1)], 1.0))
    o.display_type = "WIRE"
    mat = bpy.data.materials.new("m")
    mat.diffuse_color = color
    o.data.materials.append(mat)
    o.show_wire = True
    return o


if "--boxes" in sys.argv:
    for w in stage["walls"]:
        wire_box(w, (1, 0, 0, 0.35))
    for t in stage["triggers"]:
        wire_box(t, (0, 1, 0, 0.35))
for p in stage["players"]:
    bpy.ops.mesh.primitive_uv_sphere_add(radius=2.5, location=to_blender(p).to_translation())
for s in stage["spawns"]:
    if s["players"][0]:
        bpy.ops.mesh.primitive_cone_add(radius1=1.5, depth=5, location=to_blender(s["cf"]).to_translation() + Vector((0, 0, 2.5)))
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "TEXTURE"
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.05, 0.03, 0.08)
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
scene.collection.objects.link(cam)
scene.camera = cam
c = stage["camera"]
target = np.array(stage["players"][0][:3]) + np.array([0, 4.0, 0])  # character centre
if wide:
    c = dict(c, offset=list(np.array(c["offset"]) * 3.0))
R = np.array(c["rot"]).reshape(3, 3)
m = np.eye(4)
m[:3, :3] = B @ R  # camera-local axes are the same convention in both apps
m[:3, 3] = B @ (target + np.array(c["offset"]))
cam.matrix_world = Matrix(m.tolist())
cam.data.sensor_fit = "VERTICAL"
cam.data.angle = np.radians(c["fov"])
cam.data.clip_end = 20000
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("rendered", out)
