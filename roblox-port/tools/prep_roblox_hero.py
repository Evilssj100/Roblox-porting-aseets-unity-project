"""Make a Roblox-ready copy of a repurposed hero .blend.

* rest pose, helper objects removed, armature + meshes un-parented from the glTF empties with
  transforms applied (identity object transforms, Z-up), mesh re-parented to the armature
* mesh split by material into <Hero>_Body / <Hero>_Head; the head's UVs are remapped from
  expression tile 0 of the 4x2 face atlas to the full 0..1 range, and the 8 tiles are saved as
  separate images (<Hero>_Face_0..7.png) so Roblox can swap TextureID for expressions
* armature renamed <Hero> (data <Hero>_Rig), action slots renamed to match
* palm FX attachment points (fx_Lpalm/fx_Rpalm) recorded as bone + offset in the json
* every action sampled at 30 fps: armature-space bone matrices (world, Blender axes) saved to
  <Hero>_anim.npz for building Roblox KeyframeSequences later

Usage: python prep_roblox_hero.py <hero.blend> <face_atlas.png> <out_dir> <Hero> [body.png]
The head part is the one whose texture image (or material) is named "head"; the largest other part is
<Hero>_Body and any further materials (props, weapons) become <Hero>_Body2, ... with their own textures.
Pass body.png when the .blend's body image is packed.
"""
import json
import os
import sys

import bpy
import numpy as np
from PIL import Image

src, atlas_png, out_dir, hero = sys.argv[1:5]
tex_dir = os.path.join(out_dir, "textures")
os.makedirs(tex_dir, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=src)
scene = bpy.context.scene

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = next(o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
for o in bpy.data.objects:
    if o.animation_data:
        o.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
scene.frame_set(1)
bpy.context.view_layer.update()

# FX attachment points: empties parented to bones
fx = {}
for o in bpy.data.objects:
    if o.type == "EMPTY" and o.parent == arm and o.parent_type == "BONE":
        b = arm.data.bones[o.parent_bone]
        M = arm.matrix_world @ b.matrix_local
        off = (M.inverted() @ o.matrix_world).translation
        fx[o.name] = {"bone": o.parent_bone, "world": list(o.matrix_world.translation), "offset_in_bone": list(off)}

# un-parent first (keeping the glTF root's Y-up -> Z-up rotation), only then delete the empties
bpy.ops.object.select_all(action="DESELECT")
for o in (arm, mesh):
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
for o in list(bpy.data.objects):
    if o not in (arm, mesh):
        bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="DESELECT")
for o in (arm, mesh):
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.context.view_layer.update()
mesh.parent = arm
mesh.matrix_parent_inverse.identity()
next(m for m in mesh.modifiers if m.type == "ARMATURE").object = arm

# split by material
bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
bpy.context.view_layer.objects.active = mesh
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.separate(type="MATERIAL")
bpy.ops.object.mode_set(mode="OBJECT")
parts = [o for o in bpy.data.objects if o.type == "MESH"]


def is_head(mat):
    """The head material shows the face atlas: its image name (or failing that the material name) says 'head'."""
    tex = next((n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None) if mat and mat.node_tree else None
    if tex is not None:
        return "head" in tex.image.name.lower() or mat.name.lower().endswith("_head")
    return "head" in (mat.name if mat else "").lower()


heads, bodies = [], []
for o in parts:
    used = {p.material_index for p in o.data.polygons}
    (heads if is_head(o.material_slots[min(used)].material) else bodies).append(o)
assert len(heads) <= 1 and bodies, f"expected at most one head part and a body, got heads={[o.name for o in heads]}"
head = heads[0] if heads else None  # minions and robots: no separate head / face atlas
bodies.sort(key=lambda o: -len(o.data.vertices))  # extra materials (props, guns) stay separate parts
body = bodies[0]
extra = bodies[1:]
for i, o in enumerate(extra):
    o.name = o.data.name = f"{hero}_Body{i + 2}"
parts = [body] + ([head] if head else []) + extra
for o in parts:
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.material_slot_remove_unused()
body.name, body.data.name = f"{hero}_Body", f"{hero}_Body"
face0 = None
if head:
    head.name, head.data.name = f"{hero}_Head", f"{hero}_Head"

# rigs that hide alternative geometry with zero-scale bones (Roblox bones cannot scale): those faces become their own
# parts, shown or hidden by the runtime from the bone's scale (Config.Models[...].scaleParts)
SPLIT = {"HubPigeon": {"Wings": ["Lwing1", "Lwing2", "Rwing1", "Rwing2"], "Fold": ["l_wing1", "r_wing1"]}}
for gname, gbones in SPLIT.get(hero, {}).items():
    idx = {g.index for g in body.vertex_groups if g.name in gbones}
    nv = len(body.data.vertices)
    share, total = np.zeros(nv), np.zeros(nv)
    for v in body.data.vertices:
        for g in v.groups:
            total[v.index] += g.weight
            if g.group in idx:
                share[v.index] += g.weight
    frac = share / np.maximum(total, 1e-9)
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    picked = 0
    for poly in body.data.polygons:
        poly.select = bool(frac[list(poly.vertices)].mean() > 0.5)
        picked += poly.select
    if not picked:
        continue
    before = set(bpy.data.objects)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.separate(type="SELECTED")
    bpy.ops.object.mode_set(mode="OBJECT")
    new = next(o for o in bpy.data.objects if o not in before)
    new.name = new.data.name = f"{hero}_{gname}"
    print(f"split {picked} faces -> {new.name}")

# face tiles + head UV remap (tile 0: u in [0,.25], v in [.5,1])
atlas = Image.open(atlas_png).convert("RGB") if head else None
if head:
    T = atlas.size[0] // 4
    for k in range(8):
        i, j = k % 4, k // 4
        atlas.crop((i * T, j * T, (i + 1) * T, (j + 1) * T)).save(os.path.join(tex_dir, f"{hero}_Face_{k}.png"))
    uvl = head.data.uv_layers.active.data
    uv = np.zeros(len(uvl) * 2)
    uvl.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    print("head uv range before:", uv.min(0).round(3), uv.max(0).round(3))
    if uv[:, 0].max() > 0.2505 or uv[:, 1].min() < 0.4995:
        print("WARNING: head UVs are not inside expression tile 0 (u<=.25, v>=.5); face tiles will be wrong")
    uv[:, 0] = uv[:, 0] * 4.0
    uv[:, 1] = uv[:, 1] * 2.0 - 1.0
    uvl.foreach_set("uv", uv.ravel())
    hm = head.material_slots[0].material
    nt = hm.node_tree
    for n in list(nt.nodes):
        if n.type in ("MAPPING", "UVMAP"):
            nt.nodes.remove(n)
    tex = next(n for n in nt.nodes if n.type == "TEX_IMAGE")
    face0 = bpy.data.images.load(os.path.join(tex_dir, f"{hero}_Face_0.png"))
    face0.name = f"{hero}_Face_0"
    tex.image = face0

# body texture to file too
bm = body.material_slots[0].material
btex = next(n for n in bm.node_tree.nodes if n.type == "TEX_IMAGE")
body_png = os.path.join(tex_dir, f"{hero}_Body.png")
if len(sys.argv) > 5:  # the repurposed body texture as a file (the .blend copy is packed)
    Image.open(sys.argv[5]).convert("RGB").save(body_png)
else:
    w, h = btex.image.size
    px = np.array(btex.image.pixels[:], np.float32).reshape(h, w, -1)[::-1, :, :3]
    Image.fromarray((np.clip(px, 0, 1) * 255 + 0.5).astype(np.uint8)).save(body_png)
btex.image.name = f"{hero}_Body"
# absolute paths next to the output .blend (save_as remaps them to //textures/...), and pack both
for im, fn in ((btex.image, f"{hero}_Body.png"), (face0, f"{hero}_Face_0.png")):
    if im is None:
        continue
    if im.packed_file:
        im.unpack(method="REMOVE")
    im.filepath = os.path.abspath(os.path.join(tex_dir, fn))
    im.reload()
    im.pack()
for im in list(bpy.data.images):
    if im.users == 0:
        bpy.data.images.remove(im)

# rename rig + action slots
old_arm_name = arm.name
arm.name = hero
arm.data.name = f"{hero}_Rig"
renamed = 0
for a in bpy.data.actions:
    for s in a.slots:
        if s.identifier.startswith("OB") and s.identifier != "OB" + hero:
            try:
                s.name_display = hero
                renamed += 1
            except Exception as e:
                print("slot rename failed", a.name, e)

# ---- animation sampling (optional: the exact npz from unity_hero_anim_exact.py is the source of truth)
SAMPLE = os.environ.get("SAMPLE_ACTIONS") == "1"
bones = [b.name for b in arm.data.bones]
parents = [arm.data.bones[n].parent.name if arm.data.bones[n].parent else "" for n in bones]
rest = np.array([np.array(arm.matrix_world @ arm.data.bones[n].matrix_local) for n in bones])
clips, meta_clips = {}, []
arm.animation_data_create()
for a in (sorted(bpy.data.actions, key=lambda x: x.name) if SAMPLE else []):
    slot = next((s for s in a.slots if s.identifier == "OB" + hero), None)
    if slot is None:
        continue
    arm.animation_data.action = a
    arm.animation_data.action_slot = slot
    f0, f1 = int(round(a.frame_range[0])), int(round(a.frame_range[1]))
    frames = list(range(f0, f1 + 1))
    M = np.zeros((len(frames), len(bones), 4, 4), np.float32)
    for k, f in enumerate(frames):
        scene.frame_set(f)
        for bi, n in enumerate(bones):
            M[k, bi] = np.array(arm.matrix_world @ arm.pose.bones[n].matrix)
    clips[a.name] = M
    meta_clips.append({"name": a.name, "frames": len(frames), "duration": round((len(frames) - 1) / scene.render.fps, 4)})
arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()

np.savez_compressed(os.path.join(out_dir, f"{hero}_rig.npz"), bones=np.array(bones), parents=np.array(parents),
                    rest=rest, **{f"clip__{k}": v for k, v in clips.items()})
meta_clips = meta_clips or [{"name": a.name, "duration": a.get("duration")} for a in sorted(bpy.data.actions, key=lambda x: x.name)]
_vis = [o for o in (body, head) if o is not None]
height = max(v[2] for o in _vis for v in [o.matrix_world @ c for c in [vv.co for vv in o.data.vertices]]) - \
    min(v[2] for o in _vis for v in [o.matrix_world @ c for c in [vv.co for vv in o.data.vertices]])
json.dump({"hero": hero, "height_bu": height, "bones": bones, "parents": parents, "fx_points": fx,
           "clips": meta_clips, "face_tiles": [f"{hero}_Face_{k}.png" for k in range(8)],
           "face_tile_names": ["neutral_smile", "grin", "surprised", "gritted", "wink", "smirk", "shout", "focused"]},
          open(os.path.join(out_dir, f"{hero}_meta.json"), "w"), indent=1)

bpy.ops.object.select_all(action="DESELECT")
scene.frame_set(1)
out_blend = os.path.join(out_dir, f"{hero}.blend")
bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True, relative_remap=True)
print(f"saved {out_blend}: body {len(body.data.vertices)}v, head {len(head.data.vertices) if head else 0}v, bones {len(bones)}, "
      f"clips {len(clips)}, slots renamed {renamed}, height {height:.3f} BU, fx {list(fx)}")
