"""Verify an exact hero .blend against the original Unity skinning, vertex by vertex.

For every clip, at evenly spread original sample times, Blender's deformed mesh is compared with
    v = C · sum_j w_j · (W_exact_j(t) · bindpose_j) · v_mesh
(the original linear-blend skinning, with bone scale). Prints the worst vertex error per clip.
Usage: python exact_verify_blend.py <exact.blend> <bundle.unity3d> <anim_exact_prefix> [samples_per_clip]
"""
import json
import os
import sys

import bpy
import numpy as np
import UnityPy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unity_hero_to_glb import mat4  # noqa: E402
from UnityPy.helpers.MeshHelper import MeshHandler  # noqa: E402

blend, bundle, prefix = sys.argv[1:4]
per_clip = int(sys.argv[4]) if len(sys.argv) > 4 else 6
ex = np.load(prefix + ".npz")
meta = json.load(open(prefix + ".json"))
S4 = np.diag([-1.0, 1.0, 1.0, 1.0])
C = np.eye(4)
C[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]

env = UnityPy.load(bundle)
smr = next(o.read() for o in env.objects if o.type.name == "SkinnedMeshRenderer"
           and o.read().m_Mesh and o.read().m_Mesh.read().m_Name.lower().endswith("lod0"))
mesh = smr.m_Mesh.read()
h = MeshHandler(mesh)
h.process()
V = np.asarray(h.m_Vertices, float).reshape(-1, 3).copy()
V[:, 0] *= -1
Vh = np.c_[V, np.ones(len(V))]
Wt = np.asarray(h.m_BoneWeights, float).reshape(-1, 4)
Ji = np.asarray(h.m_BoneIndices, int).reshape(-1, 4)
bind_inv = np.stack([S4 @ mat4(bp) @ S4 for bp in mesh.m_BindPose])

bpy.ops.wm.open_mainfile(filepath=blend)
scene = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mo = next(o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
ad = arm.animation_data or arm.animation_data_create()
height = np.ptp((Vh @ (C @ ex["bind_world"][0] @ bind_inv[0]).T)[:, 2])


def blender_mesh():
    deps = bpy.context.evaluated_depsgraph_get()
    ev = mo.evaluated_get(deps)
    m = ev.to_mesh()
    co = np.empty(len(m.vertices) * 3)
    m.vertices.foreach_get("co", co)
    ev.to_mesh_clear()
    co = co.reshape(-1, 3)
    return (np.c_[co, np.ones(len(co))] @ np.array(ev.matrix_world).T)[:, :3]


worst_all = 0.0
for c in meta["clips"]:
    name = c["name"]
    act = bpy.data.actions[name]
    ad.action = act
    ad.action_slot = act.slots[0]
    W = ex[f"clip__{name}"]
    times = ex[f"times__{name}"]
    ks = np.unique(np.linspace(0, len(times) - 1, per_clip).round().astype(int))
    worst = 0.0
    for k in ks:
        scene.frame_set(int(np.floor(1 + times[k] * 60)), subframe=float((1 + times[k] * 60) % 1))
        Pb = blender_mesh()
        Sk = np.stack([C @ W[k, j] @ bind_inv[j] for j in range(len(meta["bones"]))])
        U = np.zeros_like(V)
        for col in range(4):
            U += Wt[:, col:col + 1] * np.einsum("nij,nj->ni", Sk[Ji[:, col]], Vh)[:, :3]
        worst = max(worst, float(np.linalg.norm(Pb - U, axis=1).max()))
    worst_all = max(worst_all, worst)
    flag = "" if worst < 1e-3 * height else "   <-- CHECK"
    print(f"{name:26s} worst vertex error {worst:.2e}{flag}")
print(f"ALL CLIPS: worst vertex error {worst_all:.2e} units (model height {height:.2f}) = {100 * worst_all / height:.5f}% of height")
