"""Build El Rugido from the brute hero's .blend: new textures, feet reshaped into boots
(weights untouched, so every original animation still fits), and a championship-belt buckle
skinned to the Pelvis bone. Saves the .blend and renders a preview sheet.

Usage: python build_el_rugido.py <source.blend> <work_dir> <out.blend> <preview_dir>
"""
import json
import math
import os
import sys

import bpy  # must come before bmesh in the pip build
import bmesh
import numpy as np
from mathutils import Vector

src, wd, out_blend, prev = sys.argv[1:5]
os.makedirs(os.path.dirname(out_blend), exist_ok=True)
os.makedirs(prev, exist_ok=True)
meta = json.load(open(os.path.join(wd, "el_rugido_meta.json")))
bones_meta = json.load(open(os.path.join(wd, "bones.json")))
BPOS = {b["name"]: np.array(b["head"]) for b in bones_meta["bones"]}

bpy.ops.wm.open_mainfile(filepath=src)
scene = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = next(o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
others = [o for o in bpy.data.objects if o.type == "EMPTY" and o.animation_data is not None]


def assign(obj, act):
    if obj.animation_data is None:
        obj.animation_data_create()
    ad = obj.animation_data
    ad.action = act
    if act is not None:
        ad.action_slot = next((s for s in act.slots if s.identifier == "OB" + obj.name), None)


def set_action(name):
    act = bpy.data.actions.get(name) if name else None
    assign(arm, act)
    for o in others:
        assign(o, act)
    return act


set_action(None)
for o in others:
    assign(o, None)
for pb in arm.pose.bones:
    pb.matrix_basis.identity()

# ---------------------------------------------------------------- textures
def image_node(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")


mat_body, mat_head = body.material_slots[0].material, body.material_slots[1].material
for mat, fn, nm in ((mat_body, "el_rugido_body.png", "ElRugido_Body"), (mat_head, "el_rugido_head.png", "ElRugido_Head")):
    img = bpy.data.images.load(os.path.join(wd, fn))
    img.name = nm
    img.pack()
    image_node(mat).image = img
    mat.name = nm
for im in list(bpy.data.images):
    if im.users == 0:
        bpy.data.images.remove(im)

# expression offset control on the head material (tile i of 4 x 2)
nt = mat_head.node_tree
tex = image_node(mat_head)
uvn = nt.nodes.new("ShaderNodeUVMap")
mapn = nt.nodes.new("ShaderNodeMapping")
mapn.name = "ExpressionOffset"
nt.links.new(uvn.outputs["UV"], mapn.inputs["Vector"])
nt.links.new(mapn.outputs["Vector"], tex.inputs["Vector"])


def set_expression(k):
    i, j = k % 4, k // 4
    mapn.inputs["Location"].default_value = (0.25 * i, -0.5 * j, 0.0)


# ---------------------------------------------------------------- boots
me = body.data
nv = len(me.vertices)
co = np.array([v.co[:] for v in me.vertices])
gname = {g.index: g.name for g in body.vertex_groups}
dom = []
for v in me.vertices:
    best = max(v.groups, key=lambda g: g.weight, default=None)
    dom.append(gname[best.group] if best else "")
dom = np.array(dom)
mw = np.array(body.matrix_world)
wco = (np.c_[co, np.ones(nv)] @ mw.T)[:, :3]

feet_bones = {"LLegAnkle", "LLegDigit11", "RLegAnkle", "RLegDigit11"}
is_foot = np.isin(dom, list(feet_bones))
is_shin = np.isin(dom, ["LLeg2", "RLeg2"]) & (wco[:, 2] < meta["boot_top"])
boot = is_foot | is_shin

# weld duplicates (split UV/normal seams) so smoothing never opens cracks
keys = np.round(co, 5)
_, weld = np.unique(keys, axis=0, return_inverse=True)
weld = weld.ravel()
nw = weld.max() + 1
wpos = np.zeros((nw, 3))
np.add.at(wpos, weld, co)
cnt = np.bincount(weld, minlength=nw)[:, None]
wpos /= cnt
nbrs = [set() for _ in range(nw)]
for e in me.edges:
    a, b = weld[e.vertices[0]], weld[e.vertices[1]]
    if a != b:
        nbrs[a].add(b)
        nbrs[b].add(a)
w_foot = np.zeros(nw, bool)
w_foot[weld[is_foot]] = True
w_boot = np.zeros(nw, bool)
w_boot[weld[boot]] = True
movable = np.array([w_foot[i] and all(w_boot[j] for j in nbrs[i]) for i in range(nw)])
idx = np.nonzero(movable)[0]
nb = [np.array(sorted(nbrs[i])) for i in idx]


def taubin_step(P, lam):
    Q = P.copy()
    for k, i in enumerate(idx):
        if len(nb[k]):
            Q[i] = P[i] + lam * (P[nb[k]].mean(axis=0) - P[i])
    return Q


P = wpos.copy()
for _ in range(10):
    P = taubin_step(P, 0.55)
    P = taubin_step(P, -0.58)

# welded normals from the smoothed shape
me_tmp_co = P[weld]
for i, v in enumerate(me.vertices):
    v.co = me_tmp_co[i]
me.update()
vn = np.array([v.normal[:] for v in me.vertices])
wn = np.zeros((nw, 3))
np.add.at(wn, weld, vn)
wn /= np.maximum(np.linalg.norm(wn, axis=1, keepdims=True), 1e-9)
height = wco[:, 2].max() - wco[:, 2].min()
push = np.zeros(nw)
push[w_boot] = 0.008 * height
push[w_foot] = 0.011 * height
down = wn[:, 2] < -0.5
push[down] = 0.0
P = P + wn * push[:, None]
for i, v in enumerate(me.vertices):
    v.co = P[weld[i]]
me.update()
print(f"boots: {int(boot.sum())} verts shaped, {len(idx)} welded foot verts smoothed")

# ---------------------------------------------------------------- belt buckle
co_now = np.array([v.co[:] for v in me.vertices])
wco = (np.c_[co_now, np.ones(nv)] @ mw.T)[:, :3]
bz = meta["belt_z"]
xc = float(BPOS["Pelvis"][0])
torso = np.isin(dom, ["Pelvis", "Spine", "LLeg1", "RLeg1"])
band = torso & (np.abs(wco[:, 2] - bz) < 0.07)
waist_w = 2 * np.abs(wco[band, 0] - xc).max()
front_y = wco[band & (np.abs(wco[:, 0] - xc) < 0.1), 1].min()
rx, rz, depth = 0.2 * waist_w, 0.15 * waist_w, 0.06 * waist_w

bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=40, radius1=1.0, radius2=1.0, depth=1.0)
for v in bm.verts:
    x, y, z = v.co
    v.co = Vector((x * rx, z * depth, y * rz))  # disc faces -Y
front_face = min(bm.faces, key=lambda f: f.calc_center_median().y)
back_face = max(bm.faces, key=lambda f: f.calc_center_median().y)
bmesh.ops.inset_region(bm, faces=[front_face], thickness=0.12 * rz, depth=-0.25 * depth)
uv_layer = bm.loops.layers.uv.new("UVMap")
bx, by, bs = meta["buckle_square_px"]
W, H = meta["body_size"]
front_y_local = min(v.co.y for v in bm.verts)
for f in bm.faces:
    for loop in f.loops:
        x, y, z = loop.vert.co
        if y < front_y_local + 0.3 * depth:  # front face and inset ring: map the emblem
            px = bx + (0.5 + 0.5 * x / rx) * bs
            py = by + (0.5 - 0.5 * z / rz) * bs
        else:  # sides and back: plain gold from the emblem rim
            ang = math.atan2(z, x)
            px = bx + (0.5 + 0.47 * math.cos(ang)) * bs
            py = by + (0.5 - 0.47 * math.sin(ang)) * bs
        loop[uv_layer].uv = (px / W, 1.0 - py / H)
pm = bpy.data.meshes.new("buckle")
bm.to_mesh(pm)
bm.free()
for p in pm.polygons:
    p.use_smooth = False
buckle = bpy.data.objects.new("buckle", pm)
scene.collection.objects.link(buckle)
buckle.location = (xc, front_y - depth * 0.35, bz)
buckle.data.materials.append(mat_body)
vg = buckle.vertex_groups.new(name="Pelvis")
vg.add(list(range(len(pm.vertices))), 1.0, "REPLACE")
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="DESELECT")
buckle.select_set(True)
body.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
body.name = "ElRugido"
body.data.name = "ElRugido_mesh"
print(f"buckle: {rx * 2:.3f} x {rz * 2:.3f} at z={bz:.3f}; mesh verts now {len(body.data.vertices)}")

# ---------------------------------------------------------------- save
set_action("movement_idle")
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
print("saved", out_blend)

# ---------------------------------------------------------------- previews
for o in list(bpy.data.objects):
    if o.type in ("LIGHT", "CAMERA"):
        bpy.data.objects.remove(o)
world = scene.world or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.42, 0.45, 0.52, 1)
bg.inputs[1].default_value = 0.55


def light(name, kind, energy, rot, color=(1, 1, 1), size=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if size is not None and kind == "SUN":
        ld.angle = size
    ob = bpy.data.objects.new(name, ld)
    ob.rotation_euler = [math.radians(a) for a in rot]
    scene.collection.objects.link(ob)
    return ob


light("Key", "SUN", 3.2, (52, 0, -35), (1.0, 0.95, 0.88), 0.2)
light("Fill", "SUN", 1.0, (65, 0, 140), (0.75, 0.82, 1.0), 0.5)
light("Rim", "SUN", 2.2, (110, 0, 185), (1.0, 0.92, 0.85), 0.1)
ground = bpy.data.objects.new("Ground", bpy.data.meshes.new("Ground"))
gbm = bmesh.new()
bmesh.ops.create_circle(gbm, cap_ends=True, segments=64, radius=6.0)
gbm.to_mesh(ground.data)
gbm.free()
gm = bpy.data.materials.new("GroundMat")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.32, 0.34, 0.38, 1)
gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
ground.data.materials.append(gm)
scene.collection.objects.link(ground)

cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.data.lens = 60
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 48
scene.cycles.use_denoising = True
try:
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception:
    pass
scene.render.film_transparent = False
scene.view_settings.view_transform = "Standard"


def bbox():
    deps = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(deps)
    m = ev.to_mesh()
    pts = np.array([(ev.matrix_world @ v.co)[:] for v in m.vertices])
    ev.to_mesh_clear()
    return pts.min(axis=0), pts.max(axis=0)


def shoot(tag, az, el=8.0, fill=1.25, focus=None, res=(560, 700), frame=None):
    if frame is not None:
        scene.frame_set(frame)
    lo, hi = bbox()
    ground.location = (0, 0, lo[2])
    c = (lo + hi) / 2 if focus is None else np.array(focus[0])
    span = max(hi[2] - lo[2], (hi[0] - lo[0]) * 0.8) * fill if focus is None else focus[1]
    dist = span / (2 * math.tan(math.atan(18 / cam.data.lens))) * 1.05
    a, e = math.radians(az), math.radians(el)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam.location = Vector(c) + d * dist
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    scene.render.resolution_x, scene.render.resolution_y = res
    path = os.path.join(prev, f"el_rugido__{tag}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


set_expression(0)
set_action("movement_idle")
shoot("front", 0, frame=1)
shoot("threequarter", 35, frame=1)
shoot("back", 160, frame=1)
act = set_action("attack_L3")
f0, f1 = act.frame_range
shoot("attack", 25, frame=int(f0 + 0.45 * (f1 - f0)))
act = set_action("movement_run")
f0, f1 = act.frame_range
shoot("run", 70, frame=int(f0 + 0.3 * (f1 - f0)))
set_action(None)
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
scene.frame_set(1)
hips = (xc, -0.1, meta["belt_z"] - 0.25)
shoot("hips_front", 10, el=6, focus=(hips, 1.3), res=(480, 420))
shoot("hips_back", 170, el=6, focus=(hips, 1.3), res=(480, 420))
head = np.array(BPOS["Head"])
for k in (0, 1, 2, 6):
    set_expression(k)
    shoot(f"face{k}", 14, el=4, focus=((head[0], head[1] - 0.1, head[2] + 0.12), 1.15), res=(420, 420))
set_expression(0)
print("renders done")
