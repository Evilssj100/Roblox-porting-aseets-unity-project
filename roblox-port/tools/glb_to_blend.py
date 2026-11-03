"""Import a hero GLB into a fresh Blender scene, keep every action, save a .blend,
and render a quick check sheet (rest pose + two animation frames).

Usage: python glb_to_blend.py <hero.glb> <out.blend> <out_preview_dir>
"""
import math
import os
import sys

import bpy
from mathutils import Vector

glb, out_blend, out_dir = sys.argv[1:4]
os.makedirs(out_dir, exist_ok=True)
hero = os.path.splitext(os.path.basename(glb))[0]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)

arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers)]
for a in bpy.data.actions:
    a.use_fake_user = True
print(f"[{hero}] armatures={len(arms)} meshes={len(meshes)} actions={len(bpy.data.actions)} "
      f"bones={len(arms[0].data.bones) if arms else 0} materials={len(bpy.data.materials)} images={len(bpy.data.images)}")
for m in meshes:
    mods = [md.type for md in m.modifiers]
    print(f"[{hero}] mesh {m.name}: verts={len(m.data.vertices)} groups={len(m.vertex_groups)} modifiers={mods}")

arm = arms[0]
scene = bpy.context.scene
scene.render.fps = 30

# collapse NLA so one action can be shown at a time (actions stay, with fake users)
for o in bpy.data.objects:
    if o.animation_data:
        for tr in list(o.animation_data.nla_tracks):
            o.animation_data.nla_tracks.remove(tr)
if arm.animation_data is None:
    arm.animation_data_create()

others = [o for o in bpy.data.objects if o.type == "EMPTY" and o.animation_data is not None]


def assign(obj, act):
    if obj.animation_data is None:
        obj.animation_data_create()
    ad = obj.animation_data
    ad.action = act
    if act is not None and hasattr(ad, "action_slot"):
        slot = next((s for s in act.slots if s.identifier == "OB" + obj.name), None)
        ad.action_slot = slot


def set_action(name):
    act = bpy.data.actions.get(name)
    if act is None:
        cands = [a for a in bpy.data.actions if a.name.startswith(name)]
        act = cands[0] if cands else None
    assign(arm, act)
    for o in others:
        assign(o, act)
    return act


def bbox_world():
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for m in meshes:
        ev = m.evaluated_get(deps)
        me = ev.to_mesh()
        pts += [ev.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


# lighting / camera
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.58, 0.62, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 3.0
sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
scene.collection.objects.link(sun)
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.data.type = "ORTHO"
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 24
scene.cycles.use_denoising = False
scene.render.resolution_x = 420
scene.render.resolution_y = 520
scene.render.film_transparent = False


def shoot(tag, frame=None, side=False):
    if frame is not None:
        scene.frame_set(frame)
    lo, hi = bbox_world()
    c = (lo + hi) / 2
    size = max(hi.z - lo.z, hi.x - lo.x, hi.y - lo.y) * 1.15
    cam.data.ortho_scale = size
    if side:
        cam.location = (c.x + size * 3, c.y, c.z)
        cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    else:
        cam.location = (c.x, c.y - size * 3, c.z)
        cam.rotation_euler = (math.radians(90), 0, 0)
    path = os.path.join(out_dir, f"{hero}__{tag}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path, (hi - lo)


assign(arm, None)
for o in others:
    assign(o, None)
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
_, dims = shoot("rest")
print(f"[{hero}] rest size (m): x={dims.x:.2f} y={dims.y:.2f} z={dims.z:.2f}")

for clip, frac, tag in (("movement_run", 0.25, "run"), ("attack_L1", 0.45, "attack")):
    act = set_action(clip)
    if act is None:
        print(f"[{hero}] no action {clip}")
        continue
    f0, f1 = act.frame_range
    shoot(tag, int(f0 + (f1 - f0) * frac), side=(tag == "run"))

set_action("movement_idle")
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
print(f"[{hero}] saved {out_blend} ({os.path.getsize(out_blend) // 1024} KB)")
