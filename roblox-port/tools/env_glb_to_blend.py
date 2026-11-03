"""Import an environment GLB (from unity_yaml_scene_to_glb.py) into Blender, sort collision meshes
into a hidden "Collision" collection, keep every animation, save a .blend and render overview shots.

Usage: python env_glb_to_blend.py <env.glb> <out.blend> <preview_dir> [tag]
"""
import math
import os
import sys

import bpy  # noqa: F401  (must load before bmesh/mathutils in the pip build)
import numpy as np
from mathutils import Vector

glb, out_blend, prev = sys.argv[1:4]
tag = sys.argv[4] if len(sys.argv) > 4 else os.path.splitext(os.path.basename(glb))[0]
os.makedirs(prev, exist_ok=True)
os.makedirs(os.path.dirname(out_blend), exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
scene = bpy.context.scene
scene.render.fps = 30

col = bpy.data.collections.new("Collision")
scene.collection.children.link(col)
n_col = 0
for o in list(bpy.data.objects):
    if o.name.endswith("_collision") or (o.get("collision") is True):
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
        o.hide_render = True
        o.display_type = "WIRE"
        n_col += 1
for a in bpy.data.actions:
    a.use_fake_user = True

vis = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render]
pts = []
deps = bpy.context.evaluated_depsgraph_get()
for o in vis:
    for corner in o.bound_box:
        pts.append((o.matrix_world @ Vector(corner))[:])
pts = np.array(pts)
lo, hi = pts.min(0), pts.max(0)
print(f"[{tag}] meshes={len(vis)} collision={n_col} actions={len(bpy.data.actions)} "
      f"size x={hi[0]-lo[0]:.1f} y={hi[1]-lo[1]:.1f} z={hi[2]-lo[2]:.1f}")
for a in bpy.data.actions:
    print(f"[{tag}] action {a.name}: frames {a.frame_range[0]:.0f}-{a.frame_range[1]:.0f}")

bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)

# ---- previews
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.35, 0.38, 0.45, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.7
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 2.5
sun.rotation_euler = (math.radians(40), 0, math.radians(30))
scene.collection.objects.link(sun)
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.data.lens = 28
cam.data.clip_end = 5000
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 32
scene.cycles.use_denoising = True
scene.view_settings.view_transform = "Standard"
scene.render.resolution_x, scene.render.resolution_y = 960, 600

c = (lo + hi) / 2
span = float(max(hi[0] - lo[0], hi[1] - lo[1]))


def shot(name, az, el, dist_k, look=None, frame=None):
    if frame is not None:
        scene.frame_set(frame)
    a, e = math.radians(az), math.radians(el)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    target = Vector(look if look is not None else c)
    cam.location = target + d * span * dist_k
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(prev, f"{tag}__{name}.png")
    bpy.ops.render.render(write_still=True)


shot("overview", 30, 50, 0.95, frame=1)
shot("ground", 200, 14, 0.45, look=(c[0], c[1], lo[2] + (hi[2] - lo[2]) * 0.2), frame=1)
end = max((a.frame_range[1] for a in bpy.data.actions), default=1)
shot("overview_animated", 30, 50, 0.95, frame=int(end * 0.5))
print(f"[{tag}] saved {out_blend}")
