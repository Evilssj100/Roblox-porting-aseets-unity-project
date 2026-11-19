"""Put repurposed textures on a hero's exact .blend, rename everything to the new hero, save, and render
a preview sheet (front / back in the rest pose, plus a frame of an attack and the idle).

Usage: python apply_hero_textures.py <exact.blend> <Hero> <body.png> <head_atlas.png> <out.blend> <preview.png>
The head image is the one whose name contains "head" (case-insensitive); the other textured material is the body.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

src, hero, body_png, head_png, out_blend, preview = sys.argv[1:7]
bpy.ops.wm.open_mainfile(filepath=src)
scene = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = next(o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))

KEEP = body_png == "-"  # original look: keep the bundle's own images, only rename
new_body = None if KEEP else bpy.data.images.load(os.path.abspath(body_png))
new_head = None if KEEP else bpy.data.images.load(os.path.abspath(head_png))
if not KEEP:
    new_body.name, new_head.name = f"{hero}_Body", f"{hero}_HeadAtlas"
n_body = 0
for m in mesh.data.materials:
    tex = next((n for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None) if m and m.node_tree else None
    if tex is None:
        continue
    is_head = "head" in tex.image.name.lower()
    if not KEEP:
        tex.image = new_head if is_head else new_body
    if is_head:
        m.name = f"{hero}_Head"
    else:
        n_body += 1
        m.name = f"{hero}_Body" if n_body == 1 else f"{hero}_Body{n_body}"
    if KEEP:
        tex.image.name = m.name + "_tex"
for im in list(bpy.data.images):
    if im.users == 0:
        bpy.data.images.remove(im)
for im in ((new_body, new_head) if not KEEP else [i for i in bpy.data.images if i.users]):
    if im.source == "FILE" and not im.packed_file:
        im.pack()
mesh.name = mesh.data.name = hero
arm.name = f"{hero}_Rig"
bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
if preview == "-":
    print("saved", out_blend)
    raise SystemExit(0)

# ---- preview
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.display.shading.show_specular_highlight = False
scene.render.film_transparent = False
scene.world = scene.world or bpy.data.worlds.new("W")
scene.render.resolution_x, scene.render.resolution_y = 420, 520
cam = bpy.data.objects.new("PrevCam", bpy.data.cameras.new("PrevCam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.type = "ORTHO"
deps = bpy.context.evaluated_depsgraph_get()
pts = [mesh.matrix_world @ v.co for v in mesh.evaluated_get(deps).to_mesh().vertices]
zmin, zmax = min(p.z for p in pts), max(p.z for p in pts)
xr = max(abs(p.x) for p in pts)
cam.data.ortho_scale = max(zmax - zmin, 2 * xr) * 1.12
center = Vector((0, 0, (zmin + zmax) / 2))
shots = []


def shot(tag, yaw_deg, action=None, frame=1):
    if action:
        arm.animation_data_create()
        arm.animation_data.action = bpy.data.actions[action]
        slot = next((s for s in bpy.data.actions[action].slots), None)
        if slot is not None:
            arm.animation_data.action_slot = slot
    elif arm.animation_data:
        arm.animation_data.action = None
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
    scene.frame_set(frame)
    a = math.radians(yaw_deg)
    cam.location = center + Vector((math.sin(a) * 12, -math.cos(a) * 12, 0.6))
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    path = preview + f".{tag}.png"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    shots.append(path)


shot("front", 0)
shot("back", 180)
for act, fr in (("movement_idle", 30), ("attack_L5", 60)):
    if act in bpy.data.actions:
        shot(act, 30, act, fr)
from PIL import Image  # noqa: E402

ims = [Image.open(p).convert("RGB") for p in shots]
sheet = Image.new("RGB", (sum(i.width for i in ims), ims[0].height), (60, 60, 70))
x = 0
for im in ims:
    sheet.paste(im, (x, 0))
    x += im.width
sheet.save(preview)
for p in shots:
    os.remove(p)
print("saved", out_blend, preview)
