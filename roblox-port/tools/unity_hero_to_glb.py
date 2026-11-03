"""Convert a Unity 3.5 hero bundle (SHSO format) into a self-contained GLB.

Keeps the hero's original skeleton, the LOD0 skinned mesh with its skin weights,
its textures, and every animation clip on the hero's main Animation component
(Hermite-evaluated and resampled to 30 fps). Also writes:
  textures/*.png   every texture in the bundle
  audio/*          every audio clip in the bundle (best effort)
  meta.json        bones, clip lengths, wrap modes and animation events

Unity is left-handed and glTF right-handed, so everything is mirrored across X
(positions/normals x -> -x, quaternions (x,y,z,w) -> (x,-y,-z,w), bind poses S*M*S,
triangle winding reversed) and UV v -> 1 - v.

Usage: python -I unity_hero_to_glb.py <bundle.unity3d> <out_dir>
"""
import io
import json
import os
import re
import struct
import sys

import numpy as np
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

FPS = 30.0
S4 = np.diag([-1.0, 1.0, 1.0, 1.0])


# ---------------------------------------------------------------- helpers
def comps(v, n):
    if hasattr(v, "x"):
        return [float(v.x), float(v.y), float(v.z), float(getattr(v, "w", 0.0))][:n]
    return [float(x) for x in list(v)[:n]]


def mirror_pos(p):
    return [-p[0], p[1], p[2]]


def mirror_quat(q):
    x, y, z, w = q
    q = np.array([x, -y, -z, w], dtype=np.float64)
    n = np.linalg.norm(q)
    return (q / n if n > 0 else np.array([0, 0, 0, 1.0])).tolist()


def mat4(m):
    M = np.array([[float(getattr(m, f"e{r}{c}")) for c in range(4)] for r in range(4)])
    if not np.allclose(M[3], [0, 0, 0, 1], atol=1e-4) and np.allclose(M[:, 3], [0, 0, 0, 1], atol=1e-4):
        M = M.T
    return M


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "unnamed"


def components(go):
    for c in go.m_Component:
        p = c[1] if isinstance(c, tuple) else getattr(c, "component", c)
        try:
            reader = p.deref()
        except Exception:
            continue
        yield reader.type.name, p


# ---------------------------------------------------------------- glb writer
class GLB:
    def __init__(self):
        self.bin = bytearray()
        self.j = {"asset": {"version": "2.0", "generator": "spso-port/unity_hero_to_glb"},
                  "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [], "meshes": [], "skins": [],
                  "animations": [], "materials": [], "textures": [], "images": [], "samplers": [],
                  "accessors": [], "bufferViews": []}

    def view(self, data, target=None):
        self.bin.extend(b"\0" * ((-len(self.bin)) % 4))
        off = len(self.bin)
        self.bin.extend(data)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target is not None:
            bv["target"] = target
        self.j["bufferViews"].append(bv)
        return len(self.j["bufferViews"]) - 1

    def acc(self, a, gltype, comp, target=None, minmax=False):
        a = np.ascontiguousarray(a)
        d = {"bufferView": self.view(a.tobytes(), target), "componentType": comp,
             "count": int(a.shape[0]), "type": gltype}
        if minmax:
            if a.ndim == 1:
                d["min"], d["max"] = [float(a.min())], [float(a.max())]
            else:
                d["min"] = [float(x) for x in a.min(axis=0)]
                d["max"] = [float(x) for x in a.max(axis=0)]
        self.j["accessors"].append(d)
        return len(self.j["accessors"]) - 1

    def write(self, path):
        for k in [k for k, v in self.j.items() if isinstance(v, list) and not v]:
            del self.j[k]
        self.j["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(self.j, separators=(",", ":")).encode()
        js += b" " * ((-len(js)) % 4)
        bn = bytes(self.bin) + b"\0" * ((-len(self.bin)) % 4)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bn)))
            f.write(struct.pack("<II", len(js), 0x4E4F534A))
            f.write(js)
            f.write(struct.pack("<II", len(bn), 0x004E4942))
            f.write(bn)


# ---------------------------------------------------------------- curves
def eval_curve(keys, times, dim):
    kt = np.array([k.time for k in keys], dtype=np.float64)
    kv = np.array([comps(k.value, dim) for k in keys], dtype=np.float64)
    if len(keys) == 1:
        return np.repeat(kv[:1], len(times), axis=0)
    kin = np.array([comps(k.inSlope, dim) for k in keys], dtype=np.float64)
    kout = np.array([comps(k.outSlope, dim) for k in keys], dtype=np.float64)
    idx = np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(kt) - 2)
    t0, t1 = kt[idx], kt[idx + 1]
    dt = t1 - t0
    with np.errstate(all="ignore"):
        s = np.clip(np.where(dt > 0, (times - t0) / np.where(dt > 0, dt, 1), 0), 0, 1)[:, None]
        m0 = kout[idx] * dt[:, None]
        m1 = kin[idx + 1] * dt[:, None]
        v0, v1 = kv[idx], kv[idx + 1]
        s2, s3 = s * s, s * s * s
        res = (2 * s3 - 3 * s2 + 1) * v0 + (s3 - 2 * s2 + s) * m0 + (-2 * s3 + 3 * s2) * v1 + (s3 - s2) * m1
        stepped = ~np.isfinite(m0) | ~np.isfinite(m1) | ~np.isfinite(res)
    res = np.where(stepped, v0, res)
    res[times <= kt[0]] = kv[0]
    res[times >= kt[-1]] = kv[-1]
    return res


# ---------------------------------------------------------------- mesh
def submesh_triangles(m, h):
    if hasattr(h, "get_triangles"):
        try:
            return [np.asarray(t, dtype=np.int64).reshape(-1, 3) for t in h.get_triangles()]
        except Exception:
            pass
    ib = h.m_IndexBuffer
    use16 = bool(getattr(h, "m_Use16BitIndices", True))
    if isinstance(ib, (bytes, bytearray, memoryview)):
        ib = np.frombuffer(ib, dtype=np.uint16 if use16 else np.uint32)
    ib = np.asarray(ib, dtype=np.int64)
    stride = 2 if use16 else 4
    out = []
    for sm in m.m_SubMeshes:
        start = sm.firstByte // stride
        idx = ib[start:start + sm.indexCount]
        strip = bool(getattr(sm, "isTriStrip", 0)) or getattr(sm, "topology", 0) == 1
        if strip:
            tris = []
            for i in range(len(idx) - 2):
                a, b, c = idx[i], idx[i + 1], idx[i + 2]
                if a != b and b != c and a != c:
                    tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
            out.append(np.array(tris, dtype=np.int64).reshape(-1, 3))
        else:
            out.append(idx[: len(idx) // 3 * 3].reshape(-1, 3))
    return out


def main_texture(mat):
    envs = mat.m_SavedProperties.m_TexEnvs
    items = list(envs.items()) if isinstance(envs, dict) else list(envs)
    found = []
    for it in items:
        k, v = it[0], it[1]
        name = k if isinstance(k, str) else getattr(k, "name", str(k))
        tex = getattr(v, "m_Texture", None)
        if tex is not None and getattr(tex, "m_PathID", 0):
            found.append((name, tex))
    for name, tex in found:
        if name == "_MainTex":
            return tex.read()
    return found[0][1].read() if found else None


# ---------------------------------------------------------------- main
def convert(bundle, out_dir):
    os.makedirs(os.path.join(out_dir, "textures"), exist_ok=True)
    env = UnityPy.load(bundle)
    objs = list(env.objects)

    # every texture and audio clip in the bundle
    tex_files, seen = {}, {}
    for o in objs:
        if o.type.name != "Texture2D":
            continue
        try:
            t = o.read()
            base = safe(t.m_Name)
            k = seen.get(base, 0)
            seen[base] = k + 1
            fn = f"{base}.png" if k == 0 else f"{base}_{k + 1}.png"
            t.image.save(os.path.join(out_dir, "textures", fn))
            tex_files[o.path_id] = fn
        except Exception as e:
            print("  texture failed:", repr(e))
    audio_files = []
    adir = os.path.join(out_dir, "audio")
    for o in objs:
        if o.type.name != "AudioClip":
            continue
        os.makedirs(adir, exist_ok=True)
        try:
            a = o.read()
            samples = a.samples
            for nm, data in samples.items():
                fn = safe(nm)
                with open(os.path.join(adir, fn), "wb") as f:
                    f.write(data)
                audio_files.append(fn)
        except Exception as e:
            try:
                a = o.read()
                raw = getattr(a, "m_AudioData", None)
                if raw:
                    fmt = {13: "mp3", 14: "ogg", 20: "wav"}.get(getattr(a, "m_Type", -1), "bin")
                    fn = f"{safe(a.m_Name)}.{fmt}"
                    with open(os.path.join(adir, fn), "wb") as f:
                        f.write(bytes(raw))
                    audio_files.append(fn)
            except Exception as e2:
                print("  audio failed:", repr(e), repr(e2))

    # hero prefab = GameObject whose Animation component carries the most clips
    best = None
    for o in objs:
        if o.type.name == "Animation":
            a = o.read()
            if best is None or len(a.m_Animations) > len(best.m_Animations):
                best = a
    anim = best
    root_go = anim.m_GameObject.read()
    root_tr = next(p.read() for t, p in components(root_go) if t == "Transform")

    nodes, by_pid = [], {}

    def walk(tr, parent, path):
        go = tr.m_GameObject.read()
        i = len(nodes)
        nodes.append({"name": go.m_Name, "tr": tr, "go": go, "parent": parent, "children": [], "path": path})
        by_pid[tr.object_reader.path_id] = i
        if parent is not None:
            nodes[parent]["children"].append(i)
        for ch in tr.m_Children:
            ctr = ch.read()
            walk(ctr, i, (path + "/" if path else "") + ctr.m_GameObject.read().m_Name)

    walk(root_tr, None, "")

    smrs = []
    for i, nd in enumerate(nodes):
        for t, p in components(nd["go"]):
            if t == "SkinnedMeshRenderer":
                smrs.append((i, p.read()))

    def mesh_name(s):
        return s.m_Mesh.read().m_Name if s.m_Mesh and s.m_Mesh.m_PathID else ""

    lod0 = [(i, s) for i, s in smrs if mesh_name(s).lower().endswith("lod0")]
    keep = lod0 or [max(smrs, key=lambda x: len(x[1].m_Bones))]
    keep_idx = {i for i, _ in keep}
    dropped = {i for i, s in smrs if i not in keep_idx and re.search(r"lod[1-9]$", mesh_name(s).lower())}

    def collect(i, acc):
        if i in dropped:
            return
        acc.append(i)
        for c in nodes[i]["children"]:
            collect(c, acc)

    order = []
    collect(0, order)
    new = {old: k for k, old in enumerate(order)}

    g = GLB()
    rest = {}
    for old in order:
        nd, tr = nodes[old], nodes[old]["tr"]
        t = mirror_pos(comps(tr.m_LocalPosition, 3))
        r = mirror_quat(comps(tr.m_LocalRotation, 4))
        s = comps(tr.m_LocalScale, 3)
        rest[new[old]] = (np.array(t), np.array(r), np.array(s))
        node = {"name": nd["name"]}
        if not np.allclose(t, 0):
            node["translation"] = t
        if not np.allclose(r, [0, 0, 0, 1]):
            node["rotation"] = r
        if not np.allclose(s, 1):
            node["scale"] = s
        kids = [new[c] for c in nd["children"] if c in new]
        if kids:
            node["children"] = kids
        g.j["nodes"].append(node)

    # materials / textures
    g.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})
    mat_cache = {}

    def material_index(mp):
        if mp is None or not mp.m_PathID:
            return None
        if mp.m_PathID in mat_cache:
            return mat_cache[mp.m_PathID]
        mat = mp.read()
        entry = {"name": mat.m_Name, "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0}}
        tex = main_texture(mat)
        if tex is not None:
            buf = io.BytesIO()
            tex.image.convert("RGBA").save(buf, format="PNG")
            img = len(g.j["images"])
            g.j["images"].append({"name": tex.m_Name, "mimeType": "image/png", "bufferView": g.view(buf.getvalue())})
            g.j["textures"].append({"sampler": 0, "source": img})
            entry["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(g.j["textures"]) - 1}
        g.j["materials"].append(entry)
        mat_cache[mp.m_PathID] = len(g.j["materials"]) - 1
        return mat_cache[mp.m_PathID]

    mesh_meta = []
    for i, smr in keep:
        m = smr.m_Mesh.read()
        h = MeshHandler(m)
        h.process()
        V = np.asarray(h.m_Vertices, dtype=np.float64).reshape(-1, 3).copy()
        V[:, 0] *= -1
        attrs = {"POSITION": g.acc(V.astype(np.float32), "VEC3", 5126, 34962, minmax=True)}
        if h.m_Normals is not None and len(h.m_Normals):
            Nn = np.asarray(h.m_Normals, dtype=np.float64).reshape(-1, 3).copy()
            Nn[:, 0] *= -1
            Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
            attrs["NORMAL"] = g.acc(Nn.astype(np.float32), "VEC3", 5126, 34962)
        if h.m_UV0 is not None and len(h.m_UV0):
            UV = np.asarray(h.m_UV0, dtype=np.float64).reshape(-1, 2).copy()
            UV[:, 1] = 1.0 - UV[:, 1]
            attrs["TEXCOORD_0"] = g.acc(UV.astype(np.float32), "VEC2", 5126, 34962)
        W = np.asarray(h.m_BoneWeights, dtype=np.float64).reshape(-1, 4).copy()
        J = np.asarray(h.m_BoneIndices, dtype=np.int64).reshape(-1, 4).copy()
        tot = W.sum(axis=1)
        zero = tot <= 1e-8
        W[zero] = [1, 0, 0, 0]
        J[zero] = 0
        W /= W.sum(axis=1, keepdims=True)
        J[W <= 0] = 0
        bones = [by_pid[b.m_PathID] for b in smr.m_Bones]
        assert J.max() < len(bones), "bone index out of range"
        attrs["JOINTS_0"] = g.acc(J.astype(np.uint16), "VEC4", 5123, 34962)
        attrs["WEIGHTS_0"] = g.acc(W.astype(np.float32), "VEC4", 5126, 34962)

        prims = []
        tris_all = submesh_triangles(m, h)
        mats = list(smr.m_Materials)
        big = len(V) > 65535
        for k, tris in enumerate(tris_all):
            tris = tris[:, [0, 2, 1]].reshape(-1)
            prim = {"attributes": attrs,
                    "indices": g.acc(tris.astype(np.uint32 if big else np.uint16), "SCALAR",
                                     5125 if big else 5123, 34963)}
            mi = material_index(mats[min(k, len(mats) - 1)] if mats else None)
            if mi is not None:
                prim["material"] = mi
            prims.append(prim)
        g.j["meshes"].append({"name": m.m_Name, "primitives": prims})

        ibm = np.stack([(S4 @ mat4(bp) @ S4).flatten(order="F") for bp in m.m_BindPose]).astype(np.float32)
        g.j["skins"].append({"name": nodes[i]["name"] + "_skin",
                             "joints": [new[b] for b in bones],
                             "inverseBindMatrices": g.acc(ibm, "MAT4", 5126)})
        g.j["nodes"][new[i]]["mesh"] = len(g.j["meshes"]) - 1
        g.j["nodes"][new[i]]["skin"] = len(g.j["skins"]) - 1
        mesh_meta.append({"node": nodes[i]["name"], "mesh": m.m_Name, "vertices": int(len(V)),
                          "triangles": int(sum(len(t) for t in tris_all)), "submeshes": len(tris_all),
                          "bones": [nodes[b]["name"] for b in bones]})

    # animations
    path_to = {nodes[old]["path"]: new[old] for old in order}
    clips_meta, used = [], {}
    for cp in anim.m_Animations:
        if not cp or not cp.m_PathID:
            continue
        clip = cp.read()
        base = clip.m_Name
        used[base] = used.get(base, 0) + 1
        name = base if used[base] == 1 else f"{base}_{used[base]}"
        groups = [("rotation", clip.m_RotationCurves, 4), ("translation", clip.m_PositionCurves, 3),
                  ("scale", clip.m_ScaleCurves, 3)]
        dur = 0.0
        for _, curves, _ in groups:
            for c in curves:
                if c.curve.m_Curve:
                    dur = max(dur, float(c.curve.m_Curve[-1].time))
        times = np.arange(0.0, dur + 1e-9, 1.0 / FPS)
        if len(times) == 0 or times[-1] < dur - 1e-6:
            times = np.append(times, dur)
        a = {"name": name, "samplers": [], "channels": []}
        tin = None
        skipped = 0
        for prop, curves, dim in groups:
            for c in curves:
                if c.path not in path_to or not c.curve.m_Curve:
                    skipped += 1
                    continue
                n = path_to[c.path]
                vals = eval_curve(c.curve.m_Curve, times, dim)
                if prop == "rotation":
                    vals = np.stack([vals[:, 0], -vals[:, 1], -vals[:, 2], vals[:, 3]], axis=1)
                    vals /= np.maximum(np.linalg.norm(vals, axis=1, keepdims=True), 1e-9)
                    for f in range(1, len(vals)):
                        if np.dot(vals[f], vals[f - 1]) < 0:
                            vals[f] = -vals[f]
                    restv = rest[n][1]
                    const = np.ptp(vals, axis=0).max() < 1e-6 and (np.allclose(vals[0], restv, atol=1e-5) or np.allclose(vals[0], -restv, atol=1e-5))
                elif prop == "translation":
                    vals[:, 0] *= -1
                    const = np.ptp(vals, axis=0).max() < 1e-6 and np.allclose(vals[0], rest[n][0], atol=1e-5)
                else:
                    const = np.ptp(vals, axis=0).max() < 1e-6 and np.allclose(vals[0], rest[n][2], atol=1e-5)
                if const:
                    continue
                if tin is None:
                    tin = g.acc(times.astype(np.float32), "SCALAR", 5126, minmax=True)
                out = g.acc(vals.astype(np.float32), "VEC4" if dim == 4 else "VEC3", 5126)
                a["samplers"].append({"input": tin, "output": out, "interpolation": "LINEAR"})
                a["channels"].append({"sampler": len(a["samplers"]) - 1, "target": {"node": n, "path": prop}})
        if a["channels"]:
            g.j["animations"].append(a)
        events = []
        for e in getattr(clip, "m_Events", []) or []:
            events.append({"time": float(e.time), "function": e.functionName, "data": e.data,
                           "float": float(getattr(e, "floatParameter", 0) or 0),
                           "int": int(getattr(e, "intParameter", 0) or 0)})
        clips_meta.append({"name": name, "duration": round(dur, 4), "wrapMode": int(clip.m_WrapMode),
                           "channels": len(a["channels"]), "skippedCurves": skipped, "events": events})

    hero = safe(os.path.splitext(os.path.basename(bundle))[0])
    g.write(os.path.join(out_dir, f"{hero}.glb"))
    meta = {"bundle": os.path.basename(bundle), "prefab": root_go.m_Name,
            "animationWrapMode": int(getattr(anim, "m_WrapMode", 0)),
            "nodes": [nodes[o]["path"] or nodes[o]["name"] for o in order],
            "meshes": mesh_meta, "clips": clips_meta,
            "textures": sorted(tex_files.values()), "audio": sorted(audio_files)}
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(f"{hero}: nodes={len(order)} meshes={len(mesh_meta)} "
          f"verts={sum(m['vertices'] for m in mesh_meta)} clips={len(g.j.get('animations', []))}/{len(clips_meta)} "
          f"textures={len(tex_files)} audio={len(audio_files)} glb={os.path.getsize(os.path.join(out_dir, hero + '.glb')) // 1024}KB")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
