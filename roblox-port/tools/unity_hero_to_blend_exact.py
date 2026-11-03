"""Build a hero .blend straight from the Unity bundle, exactly:

* mesh = the original LOD0 bind mesh (positions, custom normals, UVs, submesh materials, the
  original 4-bone weights), in the prefab's space (X mirrored, then Y-up -> Blender Z-up)
* armature rest = the original bind pose (from the mesh bind poses), so Blender's skinning
  (pose x rest^-1) is the same matrix as Unity's (world x bindpose)
* every clip keyed from unity_hero_anim_exact.py data at its native 60 fps, location + rotation
  + SCALE, computed from the original local transforms (no shear can appear), linear keys,
  channels reduced only where linear interpolation reproduces the samples within 1e-6
* clip events as pose markers; palm FX points as bone-parented empties
Scene fps is 60 so frame 1 + 60*t is the original sample time.

Usage: python unity_hero_to_blend_exact.py <bundle.unity3d> <anim_exact_prefix> <out.blend>
"""
import json
import os
import sys

import bpy
import numpy as np
import UnityPy
from mathutils import Matrix
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unity_hero_to_glb import components, main_texture, mat4, submesh_triangles  # noqa: E402
from UnityPy.helpers.MeshHelper import MeshHandler  # noqa: E402

bundle, prefix, out_blend = sys.argv[1:4]
ex = np.load(prefix + ".npz")
meta = json.load(open(prefix + ".json"))
bones = meta["bones"]
NB = len(bones)
S4 = np.diag([-1.0, 1.0, 1.0, 1.0])
C = np.eye(4)
C[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]  # Y-up (mirrored Unity) -> Blender Z-up
F = np.eye(4)
F[:3, :3] = [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]  # Blender bone Y axis = Unity bone X axis (bones point along X)
Fi = np.linalg.inv(F)

env = UnityPy.load(bundle)
objs = list(env.objects)
anim = None
for o in objs:
    if o.type.name == "Animation":
        a = o.read()
        if anim is None or len(a.m_Animations) > len(anim.m_Animations):
            anim = a
smr = None
for o in objs:
    if o.type.name == "SkinnedMeshRenderer":
        s = o.read()
        if s.m_Mesh and s.m_Mesh.read().m_Name.lower().endswith("lod0"):
            smr = s
mesh = smr.m_Mesh.read()
smr_bones = [b.read().m_GameObject.read().m_Name for b in smr.m_Bones]
assert smr_bones == bones, "bone order mismatch between mesh and exact data"
h = MeshHandler(mesh)
h.process()
V = np.asarray(h.m_Vertices, float).reshape(-1, 3).copy()
N = np.asarray(h.m_Normals, float).reshape(-1, 3).copy()
UV = np.asarray(h.m_UV0, float).reshape(-1, 2)
Wt = np.asarray(h.m_BoneWeights, float).reshape(-1, 4)
Ji = np.asarray(h.m_BoneIndices, int).reshape(-1, 4)
tris = submesh_triangles(mesh, h)
V[:, 0] *= -1
N[:, 0] *= -1
bind_inv = np.stack([S4 @ mat4(bp) @ S4 for bp in mesh.m_BindPose])
bind = ex["bind_world"]
MW = bind[0] @ bind_inv[0]  # mesh node world (prefab space)
P = (np.c_[V, np.ones(len(V))] @ (C @ MW).T)[:, :3]
Rn = (C @ MW)[:3, :3]
Nn = N @ np.linalg.inv(Rn).T
Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 60
scene.render.fps_base = 1.0

# ---------------------------------------------------------------- armature (bind pose)
parents = []
for b in smr.m_Bones:
    tr = b.read()
    p = tr.m_Father.read() if tr.m_Father and tr.m_Father.m_PathID else None
    pname = ""
    while p is not None:
        nm = p.m_GameObject.read().m_Name
        if nm in bones:
            pname = nm
            break
        p = p.m_Father.read() if p.m_Father and p.m_Father.m_PathID else None
    parents.append(pname)
arm_data = bpy.data.armatures.new("Rig")
arm = bpy.data.objects.new(os.path.splitext(os.path.basename(out_blend))[0] + "_Rig", arm_data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
rest = {}
for i, n in enumerate(bones):
    eb = arm_data.edit_bones.new(n)
    M = C @ bind[i] @ F
    rest[n] = M
    eb.head = (0, 0, 0)
    eb.tail = (0, 0.06, 0)
    eb.matrix = Matrix(M.tolist())
for i, n in enumerate(bones):
    if parents[i]:
        arm_data.edit_bones[n].parent = arm_data.edit_bones[parents[i]]
bpy.ops.object.mode_set(mode="OBJECT")
arm_data.display_type = "STICK"
for i, n in enumerate(bones):  # sanity: Blender rest == C bind F
    assert np.allclose(np.array(arm_data.bones[n].matrix_local), rest[n], atol=1e-4), n

# ---------------------------------------------------------------- mesh
me = bpy.data.meshes.new("Body")
faces, mat_idx = [], []
for k, t in enumerate(tris):
    for a, b_, c in t[:, [0, 2, 1]]:
        faces.append((int(a), int(b_), int(c)))
        mat_idx.append(k)
me.from_pydata(P.tolist(), [], faces)
me.update()
me.polygons.foreach_set("material_index", mat_idx)
me.polygons.foreach_set("use_smooth", [True] * len(faces))
uvl = me.uv_layers.new(name="UVMap")
loop_v = np.zeros(len(me.loops), int)
me.loops.foreach_get("vertex_index", loop_v)
uvl.data.foreach_set("uv", UV[loop_v].ravel())
me.normals_split_custom_set_from_vertices(Nn.tolist())
mo = bpy.data.objects.new(os.path.splitext(os.path.basename(out_blend))[0], me)
scene.collection.objects.link(mo)
mo.parent = arm
for n in bones:
    mo.vertex_groups.new(name=n)
for v in range(len(P)):
    for c in range(4):
        w = Wt[v, c]
        if w > 0:
            mo.vertex_groups[bones[Ji[v, c]]].add([v], float(w), "ADD")
mod = mo.modifiers.new("Armature", "ARMATURE")
mod.object = arm

# materials with the original textures
tex_dir = os.path.join(os.path.dirname(out_blend), "textures_src")
os.makedirs(tex_dir, exist_ok=True)
for k, mp in enumerate(smr.m_Materials):
    umat = mp.read()
    mat = bpy.data.materials.new(umat.m_Name)
    mat.use_nodes = True
    tex = main_texture(umat)
    if tex is not None:
        fn = os.path.join(tex_dir, tex.m_Name + ".png")
        tex.image.convert("RGBA").save(fn)
        img = bpy.data.images.load(fn)
        img.name = tex.m_Name
        img.pack()
        node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = img
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        mat.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 1.0
    me.materials.append(mat)

# ---------------------------------------------------------------- actions
bidx = {n: i for i, n in enumerate(bones)}
pidx = [bidx[p] if p else -1 for p in parents]
Lbind_inv = []
for i in range(NB):
    Lb = bind[i] if pidx[i] < 0 else np.linalg.inv(bind[pidx[i]]) @ bind[i]
    Lbind_inv.append(np.linalg.inv(Lb))


def decompose(M):
    t = M[:3, 3].copy()
    A = M[:3, :3]
    s = np.linalg.norm(A, axis=0)
    R = A / s
    if np.linalg.det(R) < 0:
        s[0] *= -1
        R[:, 0] *= -1
    q = np.array(Matrix(R.tolist()).to_quaternion())  # w, x, y, z
    return t, q, s


def reduce_keys(times, vals, tol=1e-6):
    """keep the samples linear interpolation can't reproduce within tol (per channel group)."""
    n = len(times)
    if n <= 2:
        return np.arange(n)
    if np.ptp(vals, axis=0).max() < tol:
        return np.array([0])
    keep = [0]
    i = 0
    while i < n - 1:
        j = i + 1
        while j + 1 < n:
            a = (times[i + 1:j + 2] - times[i]) / (times[j + 1] - times[i])
            pred = vals[i] + a[:, None] * (vals[j + 1] - vals[i])
            if np.abs(pred - vals[i + 1:j + 2]).max() > tol:
                break
            j += 1
        keep.append(j)
        i = j
    return np.array(sorted(set(keep)))


stats = {"keys": 0, "samples": 0}
arm.animation_data_create()
for c in meta["clips"]:
    name = c["name"]
    W = ex[f"clip__{name}"]
    times = ex[f"times__{name}"]
    T = len(times)
    frames = 1.0 + times * 60.0
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    slot = act.slots.new(id_type="OBJECT", name=arm.name)
    layer = act.layers.new("Layer")
    strip = layer.strips.new(type="KEYFRAME")
    bag = strip.channelbag(slot, ensure=True)
    for i, n in enumerate(bones):
        loc = np.zeros((T, 3))
        rot = np.zeros((T, 4))
        scl = np.zeros((T, 3))
        for k in range(T):
            L = W[k, i] if pidx[i] < 0 else np.linalg.inv(W[k, pidx[i]]) @ W[k, i]
            B = Fi @ Lbind_inv[i] @ L @ F
            loc[k], rot[k], scl[k] = decompose(B)
            if k and np.dot(rot[k], rot[k - 1]) < 0:
                rot[k] = -rot[k]
        for path, vals in (("location", loc), ("rotation_quaternion", rot), ("scale", scl)):
            idx = reduce_keys(times, vals)
            dp = f'pose.bones["{n}"].{path}'
            for comp in range(vals.shape[1]):
                fc = bag.fcurves.new(dp, index=comp, group_name=n)
                fc.keyframe_points.add(len(idx))
                co = np.empty(len(idx) * 2)
                co[0::2] = frames[idx]
                co[1::2] = vals[idx, comp]
                fc.keyframe_points.foreach_set("co", co)
                fc.keyframe_points.foreach_set("interpolation", [1] * len(idx))  # LINEAR
                fc.update()
            stats["keys"] += len(idx) * vals.shape[1]
            stats["samples"] += T * vals.shape[1]
    for e in c["events"]:
        m = act.pose_markers.new(f"{e['function']} {e['data']}".strip())
        m.frame = int(round(1 + e["time"] * 60))
    act["events_json"] = json.dumps(c["events"])
    act["duration"] = c["duration"]
    act["wrapMode"] = c["wrapMode"]
    act.frame_range = (1.0, 1.0 + c["duration"] * 60.0)
    act.use_frame_range = True
for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"

# palm FX points
for o in objs:
    if o.type.name == "GameObject":
        go = o.read()
        if go.m_Name.startswith("fx_") and "palm" in go.m_Name.lower():
            tr = next(p.read() for t, p in components(go) if t == "Transform")
            parent_name = tr.m_Father.read().m_GameObject.read().m_Name
            if parent_name in bidx and go.m_Name not in bpy.data.objects:
                lp = [-tr.m_LocalPosition.x, tr.m_LocalPosition.y, tr.m_LocalPosition.z]
                world = C @ bind[bidx[parent_name]] @ np.array([*lp, 1.0])
                e = bpy.data.objects.new(go.m_Name, None)
                e.empty_display_size = 0.05
                scene.collection.objects.link(e)
                e.parent = arm
                e.parent_type = "BONE"
                e.parent_bone = parent_name
                e.matrix_world = Matrix.Translation(world[:3])

scene.frame_start, scene.frame_end = 1, 120
bpy.ops.wm.save_as_mainfile(filepath=out_blend, compress=True)
print(f"saved {out_blend}: verts {len(P)}, faces {len(faces)}, bones {NB}, actions {len(meta['clips'])}, "
      f"keys {stats['keys']} of {stats['samples']} samples ({100 * stats['keys'] / stats['samples']:.1f}%)")
