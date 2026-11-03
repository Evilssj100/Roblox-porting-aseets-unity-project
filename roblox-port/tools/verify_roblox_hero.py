"""Reopen a Roblox-ready hero .blend and render rest / idle / attack from the front, plus print
bounds and object transforms, to confirm the export copy is upright, textured and animating.

Usage: python verify_roblox_hero.py <hero.blend> <out.png>
"""
import math
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image

blend, out_png = sys.argv[1:3]
bpy.ops.wm.open_mainfile(filepath=blend)
scene = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in bpy.data.objects:
    print(o.name, o.type, "parent", o.parent.name if o.parent else "-", "world identity:",
          np.allclose(np.array(o.matrix_world), np.eye(4), atol=1e-5))


def bounds():
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in meshes:
        ev = o.evaluated_get(deps)
        me = ev.to_mesh()
        pts += [(ev.matrix_world @ v.co)[:] for v in me.vertices]
        ev.to_mesh_clear()
    p = np.array(pts)
    return p.min(0), p.max(0)


lo, hi = bounds()
print("rest bounds", lo.round(3), hi.round(3), "height", round(hi[2] - lo[2], 3))

world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
sun = bpy.data.objects.new("S", bpy.data.lights.new("S", "SUN"))
sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
scene.collection.objects.link(sun)
cam = bpy.data.objects.new("C", bpy.data.cameras.new("C"))
cam.data.type = "ORTHO"
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x, scene.render.resolution_y = 360, 440


def set_action(name):
    arm.animation_data_create()
    a = bpy.data.actions.get(name) if name else None
    arm.animation_data.action = a
    if a is not None:
        arm.animation_data.action_slot = next((s for s in a.slots if s.identifier == "OB" + arm.name), None)
    return a


shots = []
for name, frac in ((None, 0), ("movement_idle", 0.0), ("attack_L1", 0.45), ("movement_run", 0.3)):
    a = set_action(name)
    if a is None:
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
        scene.frame_set(1)
    else:
        f0, f1 = a.frame_range
        scene.frame_set(int(f0 + (f1 - f0) * frac))
    lo, hi = bounds()
    c = (lo + hi) / 2
    cam.data.ortho_scale = max(hi[2] - lo[2], hi[0] - lo[0]) * 1.15
    cam.location = (c[0], c[1] - 10, c[2])
    cam.rotation_euler = (math.radians(90), 0, 0)
    path = out_png.replace(".png", f"_{name or 'rest'}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    shots.append(Image.open(path))
sheet = Image.new("RGB", (360 * len(shots), 440))
for k, im in enumerate(shots):
    sheet.paste(im.convert("RGB"), (k * 360, 0))
sheet.save(out_png)
print("ok", out_png)
