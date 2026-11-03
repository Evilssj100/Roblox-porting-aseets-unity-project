"""Export a hero for exact custom skinning in Roblox (EditableMesh), as binary files Studio can
download with HttpService and read with the buffer library (all little-endian).

Roblox space: R = G · C^-1 · Blender, where G = k · rot180(Y) (character faces -Z, Y up, k studs
per original unit) and C is the Y-up -> Z-up conversion used by the exact Blender build.

<out>/mesh.bin
  magic "SPSOMSH1", u32 nParts, u32 nBones
  per part: u32 nameLen, name bytes, u32 nVerts, u32 nTris
            nVerts * (f32 x,y,z)           rest position (studs)
            nVerts * (u8 b0..b3, f32 w0..w3) skin
            nTris * 3 * (u32 vert, f32 nx,ny,nz, f32 u,v)   corners (Roblox UV: v down)
<out>/clips/<clip>.bin
  magic "SPSOCLP1", u32 nSamples, u32 nBones, f32 rate
  nSamples * nBones * 12 f32   skinning matrix S = G·W(t)·bind^-1·G^-1, row-major 3x4
<out>/<tex>.rgba   raw RGBA8, top row first; sizes in manifest.json
<out>/manifest.json   bones, parts, clips (duration, samples, rate, scales, events), textures

Usage: python export_roblox_skin_data.py <roblox_ready.blend> <anim_exact_prefix> <textures_dir> <out_dir> [studs_per_unit]
"""
import json
import os
import struct
import sys

import bpy
import numpy as np
from PIL import Image

blend, prefix, tex_dir, out = sys.argv[1:5]
k = float(sys.argv[5]) if len(sys.argv) > 5 else 2.56
os.makedirs(os.path.join(out, "clips"), exist_ok=True)
ex = np.load(prefix + ".npz")
meta = json.load(open(prefix + ".json"))
bones = meta["bones"]
NB = len(bones)
C = np.eye(4)
C[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
G = np.diag([-k, k, -k, 1.0])
Gi = np.linalg.inv(G)
R = G @ np.linalg.inv(C)  # Blender world -> Roblox

bpy.ops.wm.open_mainfile(filepath=blend)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
parts = sorted([o for o in bpy.data.objects if o.type == "MESH"], key=lambda o: o.name)
for o in bpy.data.objects:
    if o.animation_data:
        o.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()

with open(os.path.join(out, "mesh.bin"), "wb") as f:
    f.write(b"SPSOMSH1")
    f.write(struct.pack("<II", len(parts), NB))
    part_meta = []
    for o in parts:
        me = o.data
        me.calc_loop_triangles()
        mw = np.array(o.matrix_world)
        co = np.array([v.co[:] for v in me.vertices])
        P = (np.c_[co, np.ones(len(co))] @ (R @ mw).T)[:, :3]
        # skin: top 4 weights, renormalised
        gname = {g.index: g.name for g in o.vertex_groups}
        bi = np.zeros((len(co), 4), np.uint8)
        bw = np.zeros((len(co), 4), np.float32)
        for v in me.vertices:
            ws = sorted([(g.weight, bones.index(gname[g.group])) for g in v.groups if gname[g.group] in bones and g.weight > 0],
                        reverse=True)[:4]
            tot = sum(w for w, _ in ws) or 1.0
            for c, (w, b) in enumerate(ws):
                bi[v.index, c] = b
                bw[v.index, c] = w / tot
        cn = np.array([n.vector[:] for n in me.corner_normals]) if hasattr(me, "corner_normals") else None
        uvl = me.uv_layers.active.data
        Rn = np.linalg.inv((R @ mw)[:3, :3]).T
        name = o.name.encode()
        f.write(struct.pack("<I", len(name)) + name)
        f.write(struct.pack("<II", len(co), len(me.loop_triangles)))
        f.write(P.astype("<f4").tobytes())
        for v in range(len(co)):
            f.write(bytes(bi[v]) + bw[v].astype("<f4").tobytes())
        corners = []
        for lt in me.loop_triangles:
            # Roblox front faces are counter-clockwise in a right-handed frame; R contains a
            # reflection (det<0 relative to Blender) only if G·C^-1 has det<0
            order = (0, 1, 2) if np.linalg.det(R[:3, :3]) > 0 else (0, 2, 1)
            for c in order:
                li = lt.loops[c]
                vi = me.loops[li].vertex_index
                n = cn[li] if cn is not None else me.loops[li].normal[:]
                n = Rn @ np.array(n)
                n /= max(np.linalg.norm(n), 1e-12)
                u, vv = uvl[li].uv
                corners.append(struct.pack("<I5f", vi, n[0], n[1], n[2], u, 1.0 - vv))
        f.write(b"".join(corners))
        mat = o.material_slots[0].material.name if o.material_slots else ""
        part_meta.append({"name": o.name, "verts": len(co), "tris": len(me.loop_triangles), "material": mat,
                          "rest_min": P.min(0).round(4).tolist(), "rest_max": P.max(0).round(4).tolist()})
print("mesh:", part_meta)

# rest-pose sanity: skinning with the identity pose must give back the rest mesh -> check S at bind
bind_inv = np.stack([np.linalg.inv(b) for b in ex["bind_world"]])
clips_meta = []
for c in meta["clips"]:
    name = c["name"]
    W = ex[f"clip__{name}"]
    T = W.shape[0]
    S = np.einsum("ij,tbjk,bkl,lm->tbim", G, W, bind_inv, Gi)[:, :, :3, :4]
    with open(os.path.join(out, "clips", f"{name}.bin"), "wb") as f:
        f.write(b"SPSOCLP1" + struct.pack("<IIf", T, NB, c["rate"]))
        f.write(S.astype("<f4").tobytes())
    sv = np.linalg.svd(W[..., :3, :3], compute_uv=False)
    scale_dev = float(np.abs(sv - 1).max())
    clips_meta.append({"name": name, "duration": c["duration"], "samples": T, "rate": c["rate"],
                       "maxScaleDeviation": round(scale_dev, 5), "scales": scale_dev > 0.005,
                       "wrapMode": c["wrapMode"], "events": c["events"]})

textures = {}
for fn in sorted(os.listdir(tex_dir)):
    if fn.endswith(".png"):
        im = Image.open(os.path.join(tex_dir, fn)).convert("RGBA")
        raw = os.path.splitext(fn)[0] + ".rgba"
        open(os.path.join(out, raw), "wb").write(im.tobytes())
        textures[os.path.splitext(fn)[0]] = {"file": raw, "size": list(im.size)}
json.dump({"hero": "ElRugido", "studsPerUnit": k, "bones": bones, "parents": meta["parents"], "parts": part_meta,
           "clips": clips_meta, "textures": textures,
           "faceExpressions": ["Normal", "Happy", "Surprised", "Aggressive", "Squint", "Blink", "Custom1", "Custom2"]},
          open(os.path.join(out, "manifest.json"), "w"), indent=1)
n_scale = sum(1 for c in clips_meta if c["scales"])
print(f"clips: {len(clips_meta)} ({n_scale} with bone scaling > 0.5%), textures {list(textures)}")
