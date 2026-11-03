"""Proof test for exact animation transfer, run in Blender (cloud).

1. Compares the hero's Blender rest mesh with the original Unity bind mesh (mirrored, Y-up -> Z-up).
2. Rebuilds one clip in Blender from the exact 60 fps Unity data using
       pose_world(b,t) = C · W_exact(b,t) · bind(b)^-1 · C^-1 · rest_world(b)
   (so every bone's skinning matrix equals Unity's), then compares Blender's deformed mesh with
   the mesh skinned the way Unity does it (linear blend, original bind poses and weights).
Usage: python exact_skin_check.py <hero.blend> <bundle.unity3d> <anim_exact.npz> <anim_exact.json> <clip>
"""
import json
import sys

import bpy
import numpy as np
import UnityPy
from mathutils import Matrix

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from unity_hero_to_glb import mat4  # noqa: E402
from UnityPy.helpers.MeshHelper import MeshHandler  # noqa: E402

blend, bundle, npz, js, clip = sys.argv[1:6]
C = np.eye(4)
C[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
Ci = np.linalg.inv(C)
S4 = np.diag([-1.0, 1.0, 1.0, 1.0])

ex = np.load(npz)
meta = json.load(open(js))
bones = meta["bones"]

# Unity mesh (LOD0) in mirrored, Y-up space, with weights and bind poses
env = UnityPy.load(bundle)
mesh = None
for o in env.objects:
    if o.type.name == "Mesh":
        m = o.read()
        if m.m_Name.lower().endswith("lod0") and (mesh is None):
            mesh = m
h = MeshHandler(mesh)
h.process()
V = np.asarray(h.m_Vertices, float).reshape(-1, 3).copy()
V[:, 0] *= -1
Wt = np.asarray(h.m_BoneWeights, float).reshape(-1, 4)
Ji = np.asarray(h.m_BoneIndices, int).reshape(-1, 4)
bind_inv = np.stack([S4 @ mat4(bp) @ S4 for bp in mesh.m_BindPose])  # mesh -> bone (mirrored)
bind_world = ex["bind_world"]  # bone world at bind (prefab-root space)
mesh_world = bind_world[0] @ bind_inv[0]  # mesh node world (same for all bones)
print("[mesh node world]\n", np.round(mesh_world, 4))
# glTF/Blender skin in the mesh's own space: express bone matrices relative to the mesh node
MWi = np.linalg.inv(mesh_world)
bind_world = np.stack([MWi @ b for b in bind_world])          # == inv(bind_inv)
EX_W = lambda arr: np.einsum("ij,...jk->...ik", MWi, arr)

bpy.ops.wm.open_mainfile(filepath=blend)
scene = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mo = next(o for o in bpy.data.objects if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers))
for o in bpy.data.objects:
    if o.animation_data:
        o.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()


def eval_mesh():
    deps = bpy.context.evaluated_depsgraph_get()
    ev = mo.evaluated_get(deps)
    me = ev.to_mesh()
    P = np.array([(ev.matrix_world @ v.co)[:] for v in me.vertices])
    ev.to_mesh_clear()
    return P


# 1) rest mesh vs Unity bind mesh (world, Z-up)
P_rest = eval_mesh()
U_rest = (np.c_[V, np.ones(len(V))] @ C.T)[:, :3]
if len(P_rest) == len(U_rest):
    d = np.linalg.norm(P_rest - U_rest, axis=1)
    print(f"[rest] Blender rest mesh vs Unity bind mesh: max {d.max():.6f}  mean {d.mean():.6f} ({len(V)} verts)")
else:
    from scipy.spatial import cKDTree
    d, _ = cKDTree(U_rest).query(P_rest)
    print(f"[rest] vertex counts differ ({len(P_rest)} vs {len(U_rest)}); nearest-vertex distance max {d.max():.6f} median {np.median(d):.6f}")

# 2) drive Blender bones with the exact formula for one clip, compare with Unity-style skinning
rest_world = {b.name: np.array(arm.matrix_world @ b.matrix_local) for b in arm.data.bones}
Wc = EX_W(ex[f"clip__{clip}"])
times = ex[f"times__{clip}"]
order = [bones.index(pb.name) for pb in arm.pose.bones]  # pose-bone order -> exact index
worst = 0.0
for k in range(0, len(times), max(1, len(times) // 8)):
    # target armature-space matrices, parents first (pose_bones are in hierarchy order)
    for pb in arm.pose.bones:
        i = bones.index(pb.name)
        target = C @ Wc[k, i] @ np.linalg.inv(bind_world[i]) @ Ci @ rest_world[pb.name]
        pb.matrix = arm.matrix_world.inverted() @ Matrix(target.tolist())
        bpy.context.view_layer.update()
    P = eval_mesh()
    # Unity skinning: v_world = sum_j w_j * (W_exact_j @ bind_inv_j) @ v_mesh ; then C
    Sk = np.stack([C @ Wc[k, j] @ bind_inv[j] for j in range(len(bones))])
    U = np.zeros_like(V)
    vh = np.c_[V, np.ones(len(V))]
    for c in range(4):
        U += Wt[:, c:c + 1] * np.einsum("nij,nj->ni", Sk[Ji[:, c]], vh)[:, :3]
    if len(P) == len(U):
        e = np.linalg.norm(P - U, axis=1).max()
    else:
        from scipy.spatial import cKDTree
        e = cKDTree(U).query(P)[0].max()
    worst = max(worst, e)
    print(f"[{clip}] t={times[k]:.3f}s  max vertex difference vs Unity skinning: {e:.6f}")
print(f"[{clip}] worst {worst:.6f} (model height ~2.8 units)")
