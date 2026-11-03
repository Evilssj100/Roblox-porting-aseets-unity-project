"""Organise the imported boss arena into collections, add a hero for scale, save, and render.

Collections: Arena (main shell), Aperture_Closed (doors shown while the floor iris is shut),
Aperture_Animated (iris leaves + sliders that play the opening animation), Rotor (spinning cog),
Collision (hidden). Saves <out.blend>; renders overview, player-eye and top views.

Usage: python arena_scene.py <arena.blend> <hero.blend> <out.blend> <preview_dir>
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

src, hero_blend, out_blend, prev = sys.argv[1:5]
os.makedirs(prev, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=src)
scene = bpy.context.scene


def root_names(o):
    names = []
    while o is not None:
        names.append(o.name)
        o = o.parent
    return names


groups = {"Arena": [], "Aperture_Closed": [], "Aperture_Animated": [], "Rotor": []}
for o in bpy.data.objects:
    if o.type != "MESH" or o.hide_render:
        continue
    chain = root_names(o)
    if any(n.startswith("SkrullShip_Boss_Arena_Aperture_closed") for n in chain):
        groups["Aperture_Closed"].append(o)
    elif any(n.startswith("SkrullShip_Boss_Arena_Aperture") for n in chain):
        groups["Aperture_Animated"].append(o)
    elif any(n.startswith("SkrullShip_Boss_arena_animated_cog") for n in chain):
        groups["Rotor"].append(o)
    else:
        groups["Arena"].append(o)
for name, objs in groups.items():
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    for o in objs:
        for uc in list(o.users_collection):
            if uc.name != "Collision":
                uc.objects.unlink(o)
        c.objects.link(o)
    print(f"{name}: {[o.name for o in objs]}")
# the closed doors and the animated iris overlap; show the closed state by default
bpy.data.collections["Aperture_Animated"].hide_render = True
bpy.data.collections["Aperture_Animated"].hide_viewport = True

# floor height = top of the closed iris doors
door = groups["Aperture_Closed"]
floor_z = max((o.matrix_world @ Vector(c)).z for o in door for c in o.bound_box) if door else 0.0
print("floor z", round(floor_z, 3))

# ---- hero for scale
with bpy.data.libraries.load(hero_blend, link=False) as (src_data, dst):
    dst.objects = [n for n in src_data.objects if n in ("ElRugido", "motion_transfer", "motion_export")]
hc = bpy.data.collections.new("Hero_ForScale")
scene.collection.children.link(hc)
hero_objs = [o for o in dst.objects if o is not None]
for o in hero_objs:
    hc.objects.link(o)
hero_arm = next(o for o in hero_objs if o.type == "ARMATURE")
top_parents = [o for o in hero_objs if o.parent is None]
lowest = None
for o in hero_objs:
    if o.type == "MESH":
        zmin = min((o.matrix_world @ Vector(c)).z for c in o.bound_box)
        lowest = zmin if lowest is None else min(lowest, zmin)
for o in top_parents:
    o.location = (o.location.x - 9.0, o.location.y + 2.0, o.location.z + floor_z - (lowest or 0.0))
    o.rotation_euler = (0, 0, math.radians(-20))
idle = bpy.data.actions.get("movement_idle")
if idle is not None:
    hero_arm.animation_data_create()
    hero_arm.animation_data.action = idle
    hero_arm.animation_data.action_slot = next((s for s in idle.slots if s.identifier == "OB" + hero_arm.name), None)

bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
print("saved", out_blend)

# ---- renders
for o in list(bpy.data.objects):
    if o.type in ("CAMERA", "LIGHT"):
        bpy.data.objects.remove(o)
world = scene.world or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.06, 0.1, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
for name, energy, rot, color in (("Key", 2.6, (45, 0, 35), (0.95, 0.97, 1.0)), ("Fill", 0.8, (60, 0, 200), (0.6, 0.75, 1.0))):
    lt = bpy.data.objects.new(name, bpy.data.lights.new(name, "SUN"))
    lt.data.energy = energy
    lt.data.color = color
    lt.rotation_euler = [math.radians(a) for a in rot]
    scene.collection.objects.link(lt)
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.data.clip_end = 5000
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 40
scene.cycles.use_denoising = True
scene.view_settings.view_transform = "Standard"
scene.render.resolution_x, scene.render.resolution_y = 1100, 640


def shot(name, loc, look, lens=24, frame=1):
    scene.frame_set(frame)
    cam.data.lens = lens
    cam.location = Vector(loc)
    d = (Vector(look) - Vector(loc)).normalized()
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(prev, f"arena__{name}.png")
    bpy.ops.render.render(write_still=True)


fz = floor_z
shot("overview", (34, -52, fz + 40), (0, 4, fz - 2), lens=24)
shot("player_eye", (-2, -26, fz + 4.5), (-9, 6, fz + 1.5), lens=22)
shot("top", (0, 3, fz + 95), (0, 3.01, fz), lens=30)
print("renders done")
