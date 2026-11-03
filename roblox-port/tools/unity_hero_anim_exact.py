"""Exact animation extraction straight from a Unity 3.5 hero bundle (no GLB/Blender round trip).

For every clip on the hero's main Animation component:
  * samples the original curves at the clip's native sample rate (60 fps), with Unity's own
    per-component Hermite evaluation (quaternions normalised afterwards), stepped keys honoured
  * composes full node chains, so animated ancestors (export_node, motion_transfer) are included
  * stores, for each skinned bone, its world matrix relative to the prefab root, in right-handed
    space (Unity X mirrored, Y up), plus the bind-pose world matrix of every bone
  * stores the motion_export root-motion track (local position + rotation) per sample
  * stores the clip's events (OnFaceAnimTag, OnCollision*, OnChainAttack, OnFootstep...)

Output: <out>.npz (arrays) and <out>.json (clip list, events, bones, sample rate).
Usage: python unity_hero_anim_exact.py <bundle.unity3d> <out_prefix> [fps]
"""
import json
import sys

import numpy as np
import UnityPy

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from unity_hero_to_glb import comps, components, eval_curve, mat4  # noqa: E402

S4 = np.diag([-1.0, 1.0, 1.0, 1.0])


def quat_to_m3(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def trs(t, q, s):
    M = np.eye(4)
    M[:3, :3] = quat_to_m3(q) * np.asarray(s)[None, :]
    M[:3, 3] = t
    return M


def main(bundle, out, fps=None):
    env = UnityPy.load(bundle)
    objs = list(env.objects)
    anim = None
    for o in objs:
        if o.type.name == "Animation":
            a = o.read()
            if anim is None or len(a.m_Animations) > len(anim.m_Animations):
                anim = a
    root_go = anim.m_GameObject.read()
    root_tr = next(p.read() for t, p in components(root_go) if t == "Transform")

    nodes, by_pid = [], {}

    def walk(tr, parent, path):
        go = tr.m_GameObject.read()
        i = len(nodes)
        nodes.append({"name": go.m_Name, "parent": parent, "path": path, "go": go,
                      "t": comps(tr.m_LocalPosition, 3), "q": comps(tr.m_LocalRotation, 4), "s": comps(tr.m_LocalScale, 3)})
        by_pid[tr.object_reader.path_id] = i
        for ch in tr.m_Children:
            c = ch.read()
            walk(c, i, (path + "/" if path else "") + c.m_GameObject.read().m_Name)

    walk(root_tr, None, "")
    path_idx = {n["path"]: i for i, n in enumerate(nodes)}

    smr = None
    for n in nodes:
        for t, p in components(n["go"]):
            if t == "SkinnedMeshRenderer":
                s = p.read()
                if s.m_Mesh and s.m_Mesh.read().m_Name.lower().endswith("lod0"):
                    smr, mesh_node = s, nodes.index(n)
    bones = [by_pid[b.m_PathID] for b in smr.m_Bones]
    bone_names = [nodes[b]["name"] for b in bones]
    mesh = smr.m_Mesh.read()

    def world_chain(local):
        """local: dict node->4x4 (right-handed). Returns world matrices for all nodes."""
        W = [None] * len(nodes)
        for i, n in enumerate(nodes):
            W[i] = local[i] if n["parent"] is None else W[n["parent"]] @ local[i]
        return W

    def rest_local(i):
        n = nodes[i]
        t = [-n["t"][0], n["t"][1], n["t"][2]]
        q = [n["q"][0], -n["q"][1], -n["q"][2], n["q"][3]]
        return trs(t, q, n["s"])

    rest_loc = [rest_local(i) for i in range(len(nodes))]
    rest_world = world_chain(rest_loc)
    # bind pose: joint world = mesh_node_world @ inverse(bindpose), mirrored
    bind = np.stack([np.linalg.inv(S4 @ mat4(bp) @ S4) for bp in mesh.m_BindPose])
    bind_world = np.stack([rest_world[mesh_node] @ b for b in bind])

    me_idx = path_idx.get("export_node/motion_export")
    out_arrays = {"bind_world": bind_world.astype(np.float64),
                  "rest_world": np.stack([rest_world[b] for b in bones])}
    clips_meta, used = [], {}
    for cp in anim.m_Animations:
        if not cp or not cp.m_PathID:
            continue
        clip = cp.read()
        name = clip.m_Name
        used[name] = used.get(name, 0) + 1
        if used[name] > 1:
            name = f"{name}_{used[name]}"
        rate = float(fps or clip.m_SampleRate or 60.0)
        dur = 0.0
        for cs in (clip.m_RotationCurves, clip.m_PositionCurves, clip.m_ScaleCurves):
            for c in cs:
                if c.curve.m_Curve:
                    dur = max(dur, float(c.curve.m_Curve[-1].time))
        n = int(np.floor(dur * rate + 1e-6)) + 1
        times = np.arange(n) / rate
        if times[-1] < dur - 1e-6:
            times = np.append(times, dur)
        T = len(times)
        # per-node local channels (start from rest), Unity handedness, then mirror
        loc_t = {i: np.tile(nodes[i]["t"], (T, 1)).astype(np.float64) for i in range(len(nodes))}
        loc_q = {i: np.tile(nodes[i]["q"], (T, 1)).astype(np.float64) for i in range(len(nodes))}
        loc_s = {i: np.tile(nodes[i]["s"], (T, 1)).astype(np.float64) for i in range(len(nodes))}
        missing = 0
        for cs, store, dim in ((clip.m_RotationCurves, loc_q, 4), (clip.m_PositionCurves, loc_t, 3), (clip.m_ScaleCurves, loc_s, 3)):
            for c in cs:
                i = path_idx.get(c.path)
                if i is None or not c.curve.m_Curve:
                    missing += 1
                    continue
                v = eval_curve(c.curve.m_Curve, times, dim)
                if dim == 4:
                    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
                store[i] = v
        W = np.zeros((T, len(bones), 4, 4))
        root_pos = np.zeros((T, 3))
        root_rot = np.zeros((T, 4))
        for k in range(T):
            local = []
            for i in range(len(nodes)):
                t = loc_t[i][k]
                q = loc_q[i][k]
                local.append(trs([-t[0], t[1], t[2]], [q[0], -q[1], -q[2], q[3]], loc_s[i][k]))
            Wk = world_chain(local)
            W[k] = np.stack([Wk[b] for b in bones])
            if me_idx is not None:
                t = loc_t[me_idx][k]
                q = loc_q[me_idx][k]
                root_pos[k] = [-t[0], t[1], t[2]]
                root_rot[k] = [q[0], -q[1], -q[2], q[3]]
        out_arrays[f"clip__{name}"] = W
        out_arrays[f"times__{name}"] = times
        out_arrays[f"rootpos__{name}"] = root_pos
        out_arrays[f"rootrot__{name}"] = root_rot
        events = [{"time": float(e.time), "function": e.functionName, "data": e.data,
                   "float": float(getattr(e, "floatParameter", 0) or 0), "int": int(getattr(e, "intParameter", 0) or 0)}
                  for e in (getattr(clip, "m_Events", []) or [])]
        rm = float(np.abs(root_pos - root_pos[:1]).max()) if me_idx is not None else 0.0
        clips_meta.append({"name": name, "duration": round(dur, 6), "samples": T, "rate": rate,
                           "wrapMode": int(clip.m_WrapMode), "events": events, "missingCurves": missing,
                           "rootMotionRange": round(rm, 4)})
    np.savez_compressed(out + ".npz", **out_arrays)
    json.dump({"bundle": bundle.rsplit("/", 1)[-1], "bones": bone_names,
               "parents": [nodes[nodes[b]["parent"]]["name"] if nodes[b]["parent"] is not None else "" for b in bones],
               "clips": clips_meta, "space": "right-handed (Unity X mirrored), Y up, relative to prefab root"},
              open(out + ".json", "w"), indent=1)
    print(f"{len(clips_meta)} clips, {len(bones)} bones, samples {sum(c['samples'] for c in clips_meta)}, "
          f"rate {clips_meta[0]['rate']}, root-motion clips {sum(1 for c in clips_meta if c['rootMotionRange'] > 0.01)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None)
