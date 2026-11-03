"""Bake per-texel lookup maps for a hero's textures, so textures can be repainted by body part.

For every material on the hero's skinned mesh this writes, at the texture's resolution:
  <tex>.png            the original texture (as used by the material)
  <tex>__pos.npy       rest-pose model-space position per texel (H, W, 3) float32, NaN where empty
  <tex>__nrm.npy       rest-pose normal per texel (H, W, 3) float32
  <tex>__bone.npy      dominant bone index per texel (H, W) int16, -1 where empty
  <tex>__labels.png    false-colour picture of the bone map with a legend in bones.json
and bones.json listing bone names and each bone's rest head/tail position.

Coordinates are Blender's (Z up, model faces -Y). Image rows are top-down (PIL order).

Usage: python uv_bake_maps.py <hero.blend> <out_dir>
"""
import json
import os
import sys

import bpy
import numpy as np

blend, out_dir = sys.argv[1:3]
os.makedirs(out_dir, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=blend)

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh_obj = next(o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
me = mesh_obj.data
mw = np.array(mesh_obj.matrix_world)

# make sure we read the rest pose
for o in bpy.data.objects:
    if o.animation_data:
        o.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()

bone_names = [b.name for b in arm.data.bones]
bone_index = {n: i for i, n in enumerate(bone_names)}
amw = np.array(arm.matrix_world)
bones_json = []
for b in arm.data.bones:
    h = (amw @ np.array([*b.head_local, 1.0]))[:3]
    t = (amw @ np.array([*b.tail_local, 1.0]))[:3]
    bones_json.append({"name": b.name, "head": h.round(4).tolist(), "tail": t.round(4).tolist(),
                       "parent": b.parent.name if b.parent else None})

nv = len(me.vertices)
co = np.empty(nv * 3, dtype=np.float64)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
co = (np.c_[co, np.ones(nv)] @ mw.T)[:, :3]
no = np.empty(nv * 3, dtype=np.float64)
me.vertices.foreach_get("normal", no)
no = no.reshape(-1, 3) @ np.linalg.inv(mw[:3, :3])  # normals: inverse-transpose; transpose applied by row-vector form
no /= np.maximum(np.linalg.norm(no, axis=1, keepdims=True), 1e-9)

# per-vertex weights as sparse lists, mapped to armature bone indices
group_to_bone = {g.index: bone_index.get(g.name, -1) for g in mesh_obj.vertex_groups}
vw = []
for v in me.vertices:
    d = {}
    for g in v.groups:
        b = group_to_bone.get(g.group, -1)
        if b >= 0 and g.weight > 0:
            d[b] = d.get(b, 0.0) + g.weight
    vw.append(d)

me.calc_loop_triangles()
uv_layer = me.uv_layers.active.data
tris = me.loop_triangles

summary = {"bones": bones_json, "textures": {}}
palette = np.random.default_rng(7).integers(40, 255, size=(len(bone_names), 3)).astype(np.uint8)

for mi, slot in enumerate(mesh_obj.material_slots):
    mat = slot.material
    img = None
    if mat and mat.use_nodes:
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                img = n.image
                break
    if img is None:
        continue
    W, H = img.size
    name = img.name.rsplit(".", 1)[0]
    px = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)[::-1]  # to top-down
    from PIL import Image
    Image.fromarray((np.clip(px, 0, 1) * 255 + 0.5).astype(np.uint8)).save(os.path.join(out_dir, f"{name}.png"))

    pos = np.full((H, W, 3), np.nan, dtype=np.float32)
    nrm = np.zeros((H, W, 3), dtype=np.float32)
    bone = np.full((H, W), -1, dtype=np.int16)
    count = 0
    for t in tris:
        if t.material_index != mi:
            continue
        count += 1
        vi = list(t.vertices)
        uv = np.array([uv_layer[l].uv[:] for l in t.loops], dtype=np.float64)
        # pixel-space (x right, y down), pixel centres at +0.5
        P = np.stack([uv[:, 0] * W, (1.0 - uv[:, 1]) * H], axis=1)
        x0, y0 = np.floor(P.min(axis=0)).astype(int)
        x1, y1 = np.ceil(P.max(axis=0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, W - 1), min(y1, H - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a, b, c = P
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        l0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / den
        l1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / den
        l2 = 1.0 - l0 - l1
        eps = -0.75 / max(abs(den), 1.0) ** 0.5  # small tolerance to close seams between triangles
        inside = (l0 >= eps) & (l1 >= eps) & (l2 >= eps)
        if not inside.any():
            continue
        L = np.stack([l0[inside], l1[inside], l2[inside]], axis=1)
        L = np.clip(L, 0, None)
        L /= L.sum(axis=1, keepdims=True)
        yy = (ys[inside] - 0.5).astype(int)
        xx = (xs[inside] - 0.5).astype(int)
        pos[yy, xx] = L @ co[vi]
        n = L @ no[vi]
        nrm[yy, xx] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        cand = sorted(set(vw[vi[0]]) | set(vw[vi[1]]) | set(vw[vi[2]]))
        if cand:
            Wt = np.array([[vw[v].get(bb, 0.0) for bb in cand] for v in vi])  # 3 x k
            bone[yy, xx] = np.array(cand, dtype=np.int16)[np.argmax(L @ Wt, axis=1)]
    np.save(os.path.join(out_dir, f"{name}__pos.npy"), pos)
    np.save(os.path.join(out_dir, f"{name}__nrm.npy"), nrm)
    np.save(os.path.join(out_dir, f"{name}__bone.npy"), bone)
    vis = np.zeros((H, W, 3), dtype=np.uint8)
    m = bone >= 0
    vis[m] = palette[bone[m]]
    Image.fromarray(vis).save(os.path.join(out_dir, f"{name}__labels.png"))
    used = sorted({bone_names[i] for i in np.unique(bone[m])})
    summary["textures"][name] = {"material": mat.name, "size": [W, H], "triangles": count,
                                 "coverage": round(float(m.mean()), 3), "bones_used": used}
    print(f"{name}: {W}x{H} tris={count} coverage={m.mean():.1%} bones={len(used)}")

summary["palette"] = {bone_names[i]: palette[i].tolist() for i in range(len(bone_names))}
with open(os.path.join(out_dir, "bones.json"), "w") as f:
    json.dump(summary, f, indent=1)
