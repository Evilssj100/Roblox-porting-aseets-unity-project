"""Build a hero's Roblox runtime pack: the ORIGINAL Unity animation curves (Hermite keys, exactly as
the game evaluated them), converted to Roblox space, plus the skinned mesh and bind data, in one
zstd-compressed binary. The Roblox runtime (SPSO ExactAnimator) evaluates the curves at any frame
time, so playback matches the original game at every frame, not just at 60 fps sample times.

Space conversion (Unity left-handed local TRS -> Roblox, k studs per unit; Z mirror + scale):
  position (x, y, z) -> (k x, k y, -k z)      rotation (x, y, z, w) -> (-x, -y, z, w)      scale unchanged
Hermite evaluation is linear in values and slopes, so keys and slopes are converted the same way.

Pack (little-endian, then zstd level 19):
  "SPSOHRO1" u32 version f32 studs str hero
  u16 nNodes  { str name, i16 parent, f32 t[3], f32 q[4], f32 s[3] }            rest local TRS
  u16 nBones  { u16 node, f32 binv[12], f32 radius }                           skin order
  u16 nParts  { str name, u32 nV, f32 pos[3nV], u8 bi[4nV], f32 bw[4nV],
                u32 nN, {u32 vert, f32 n[3]}, u32 nUV, f32 uv[2nUV], u32 nT, u32 tri[9nT] }
  u16 nClips  { str name, f32 duration, f32 rate, u8 wrap, u8 flags(1=root motion),
                u16 nEvents { f32 time, str fn, str data, f32 f, i32 i },
                u16 nCurves { u16 node, u8 kind(0 rot,1 pos,2 scl), u8 flags(1=constant),
                              flags 1 constant: f32 v[dim]
                              else u16 n, time[n] (flags&2: u16 frame, time = f32(frame/rate); else f32),
                                   f32 v[n*dim], f32 in[n*dim],
                                   flags&4: u8 mask[ceil(n/8)] (bit k = key k's out slope differs),
                                            f32 out[popcount*dim]; otherwise out = in } }
  u16 nTests  { u16 clip, f32 time, f32 S[nBones*12] }                          self-test samples
  u16 nSigs   { u16 clip, f32 time, f64 signature }      every clip: sum_b sum_ij S_b[ij]*(b+1)*(ij+1)
  (str = u16 length + utf-8 bytes; binv/S = 3x4 row-major; tri = v0 v1 v2 n0 n1 n2 uv0 uv1 uv2, 0-based)

Usage: python spso_hero_pack.py <bundle.unity3d> <mesh.bin> <Hero> <out_dir> [--studs 2.56] [--exact <anim_exact_prefix>]
  --exact: also check every 60 fps sample of every clip against unity_hero_anim_exact.py output.
"""
import argparse
import base64
import json
import os
import struct
import sys

import numpy as np
import UnityPy
import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unity_hero_to_glb import comps, components, mat4  # noqa: E402
from spso_names import clean  # noqa: E402

S4 = np.diag([-1.0, 1.0, 1.0, 1.0])
DIM = {0: 4, 1: 3, 2: 3}


def q2m(q):
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
                     np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
                     np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], -2)


def trs(t, q, s):
    M = np.zeros(np.shape(t)[:-1] + (4, 4))
    M[..., :3, :3] = q2m(q) * np.asarray(s)[..., None, :]
    M[..., :3, 3] = t
    M[..., 3, 3] = 1
    return M


def hermite(times, vals, ins, outs, t):
    """Unity AnimationCurve evaluation (same as unity_hero_to_glb.eval_curve) for one curve, many t."""
    t = np.atleast_1d(np.asarray(t, np.float64))
    if len(times) == 1:
        return np.repeat(vals[:1], len(t), 0)
    idx = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 2)
    t0, t1 = times[idx], times[idx + 1]
    dt = t1 - t0
    with np.errstate(all="ignore"):
        u = np.clip(np.where(dt > 0, (t - t0) / np.where(dt > 0, dt, 1), 0), 0, 1)[:, None]
        m0 = outs[idx] * dt[:, None]
        m1 = ins[idx + 1] * dt[:, None]
        v0, v1 = vals[idx], vals[idx + 1]
        u2, u3 = u * u, u * u * u
        r = (2 * u3 - 3 * u2 + 1) * v0 + (u3 - 2 * u2 + u) * m0 + (-2 * u3 + 3 * u2) * v1 + (u3 - u2) * m1
        stepped = ~np.isfinite(m0) | ~np.isfinite(m1) | ~np.isfinite(r)
    r = np.where(stepped, v0, r)
    r[t <= times[0]] = vals[0]
    r[t >= times[-1]] = vals[-1]
    return r


def conv(kind, v, k):
    """Unity-space (left-handed) values/slopes -> Roblox space (array [..., dim])."""
    v = np.array(v, np.float64)
    if kind == 0:
        v[..., 0] *= -1
        v[..., 1] *= -1
    elif kind == 1:
        v *= k
        v[..., 2] *= -1
    return v


class Hero:
    def __init__(self, bundle, k):
        self.k = k
        env = UnityPy.load(bundle)
        anim = None
        for o in env.objects:
            if o.type.name == "Animation":
                a = o.read()
                if anim is None or len(a.m_Animations) > len(anim.m_Animations):
                    anim = a
        self.anim = anim
        root_tr = next(p.read() for t, p in components(anim.m_GameObject.read()) if t == "Transform")
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
        from unity_mesh_compat import pick_skinned_renderer
        cands = []
        for i, n in enumerate(nodes):
            for t, p in components(n["go"]):
                if t == "SkinnedMeshRenderer":
                    cands.append((p.read(), i))
        smr = pick_skinned_renderer([c[0] for c in cands])
        mesh_node = next(i for s_, i in cands if s_ is smr)
        self.skin_nodes = [by_pid[b.m_PathID] for b in smr.m_Bones]
        mesh = smr.m_Mesh.read()
        # bind pose world (right-handed), as in unity_hero_anim_exact.py
        rest_loc = [trs(np.array([-n["t"][0], n["t"][1], n["t"][2]]), np.array([n["q"][0], -n["q"][1], -n["q"][2], n["q"][3]]),
                        np.array(n["s"])) for n in nodes]
        rest_world = []
        for i, n in enumerate(nodes):
            rest_world.append(rest_loc[i] if n["parent"] is None else rest_world[n["parent"]] @ rest_loc[i])
        bind = np.stack([np.linalg.inv(S4 @ mat4(bp) @ S4) for bp in mesh.m_BindPose])
        self.bind_world = np.stack([rest_world[mesh_node] @ b for b in bind])
        # clips (same naming as unity_hero_anim_exact.py)
        self.clips, used = [], {}
        path_idx = {n["path"]: i for i, n in enumerate(nodes)}
        animated = set()
        for cp in anim.m_Animations:
            if not cp or not cp.m_PathID:
                continue
            clip = cp.read()
            name = clip.m_Name
            used[name] = used.get(name, 0) + 1
            if used[name] > 1:
                name = f"{name}_{used[name]}"
            curves, dur = [], 0.0
            for kind, cs in ((0, clip.m_RotationCurves), (1, clip.m_PositionCurves), (2, clip.m_ScaleCurves)):
                for c in cs:
                    i = path_idx.get(c.path)
                    if i is None or not c.curve.m_Curve:
                        continue
                    ks = c.curve.m_Curve
                    d = DIM[kind]
                    curves.append({"node": i, "kind": kind,
                                   "t": np.array([kk.time for kk in ks], np.float64),
                                   "v": conv(kind, [comps(kk.value, d) for kk in ks], k),
                                   "in": conv(kind, [comps(kk.inSlope, d) for kk in ks], k),
                                   "out": conv(kind, [comps(kk.outSlope, d) for kk in ks], k)})
                    animated.add(i)
                    dur = max(dur, float(ks[-1].time))
            events = [{"time": float(e.time), "function": e.functionName, "data": e.data or "",
                       "float": float(getattr(e, "floatParameter", 0) or 0), "int": int(getattr(e, "intParameter", 0) or 0)}
                      for e in (getattr(clip, "m_Events", []) or [])]
            self.clips.append({"name": name, "duration": dur, "rate": float(clip.m_SampleRate or 60.0),
                               "wrap": int(clip.m_WrapMode), "curves": curves, "events": events})
        # runtime nodes: skinned bones, animated nodes, and all their ancestors (parent-first order)
        keep = set()
        for i in list(self.skin_nodes) + sorted(animated):
            while i is not None and i not in keep:
                keep.add(i)
                i = nodes[i]["parent"]
        order = [i for i in range(len(nodes)) if i in keep]  # walk() is depth-first: parents first
        self.remap = {old: new for new, old in enumerate(order)}
        self.nodes = []
        for old in order:
            n = nodes[old]
            self.nodes.append({"name": n["name"], "path": n["path"],
                               "parent": self.remap[n["parent"]] if n["parent"] is not None else -1,
                               "t": conv(1, n["t"], k), "q": conv(0, n["q"], k), "s": np.array(n["s"], np.float64)})
        self.bones = [self.remap[i] for i in self.skin_nodes]
        for c in self.clips:
            for cv in c["curves"]:
                cv["node"] = self.remap[cv["node"]]
            me = self.find("motion_export")
            c["root_motion"] = any(cv["node"] == me and cv["kind"] == 1 and np.abs(cv["v"] - cv["v"][:1]).max() > 1e-6
                                   for cv in c["curves"]) if me is not None else False
        G = np.diag([-k, k, -k, 1.0])
        self.G, self.Gi = G, np.linalg.inv(G)
        self.binv = np.stack([np.linalg.inv(G @ b @ self.Gi) for b in self.bind_world])  # Roblox-space bind inverse

    def find(self, name):
        return next((i for i, n in enumerate(self.nodes) if n["name"] == name), None)

    def local_at(self, clip, t):
        """local TRS of every runtime node at clip time(s) t -> (T, N, 3/4/3)"""
        t = np.atleast_1d(np.asarray(t, np.float64))
        N = len(self.nodes)
        lt = np.tile(np.stack([n["t"] for n in self.nodes]), (len(t), 1, 1))
        lq = np.tile(np.stack([n["q"] for n in self.nodes]), (len(t), 1, 1))
        ls = np.tile(np.stack([n["s"] for n in self.nodes]), (len(t), 1, 1))
        for cv in clip["curves"]:
            v = hermite(cv["t"], cv["v"], cv["in"], cv["out"], t)
            (lq, lt, ls)[cv["kind"]][:, cv["node"]] = v
        lq = lq / np.maximum(np.linalg.norm(lq, axis=-1, keepdims=True), 1e-12)
        return lt, lq, ls

    def worlds(self, lt, lq, ls):
        L = trs(lt, lq, ls)
        W = np.empty_like(L)
        for i, n in enumerate(self.nodes):
            W[:, i] = L[:, i] if n["parent"] < 0 else W[:, n["parent"]] @ L[:, i]
        return W

    def skin_mats(self, clip, t):
        W = self.worlds(*self.local_at(clip, t))
        return np.einsum("tbij,bjk->tbik", W[:, self.bones], self.binv)


def signature(S):
    """S: (nBones, 4, 4) -> weighted sum used by the runtime to prove every clip decodes and evaluates right"""
    wgt = np.arange(1, len(S) + 1)[:, None, None] * np.arange(1, 13).reshape(1, 3, 4)
    return float((S[:, :3, :4] * wgt).sum())


def read_mesh_bin(path):
    d = open(path, "rb").read()
    assert d[:8] == b"SPSOMSH1", "not a SPSOMSH1 mesh file"
    nP, nB = struct.unpack_from("<II", d, 8)
    o, parts = 16, []
    for _ in range(nP):
        (nl,) = struct.unpack_from("<I", d, o)
        o += 4
        name = d[o:o + nl].decode()
        o += nl
        nV, nT = struct.unpack_from("<II", d, o)
        o += 8
        P = np.frombuffer(d, "<f4", nV * 3, o).reshape(nV, 3).astype(np.float64)
        o += nV * 12
        sk = np.frombuffer(d, np.dtype([("b", "u1", 4), ("w", "<f4", 4)]), nV, o)
        o += nV * 20
        cr = np.frombuffer(d, np.dtype([("v", "<u4"), ("n", "<f4", 3), ("uv", "<f4", 2)]), nT * 3, o)
        o += nT * 3 * 24
        parts.append({"name": name, "P": P, "bi": sk["b"].astype(int), "bw": sk["w"].astype(np.float64), "corners": cr})
    return parts, nB


class W:
    def __init__(self):
        self.b = bytearray()

    def pack(self, fmt, *v):
        self.b += struct.pack("<" + fmt, *v)

    def str(self, s):
        e = s.encode()
        self.pack("H", len(e))
        self.b += e

    def f32(self, a):
        self.b += np.asarray(a, "<f4").tobytes()


def build(args):
    hero = Hero(args.bundle, args.studs)
    parts, nB = read_mesh_bin(args.mesh)
    NB = len(hero.bones)
    assert nB == NB, f"mesh has {nB} bones, bundle skin has {NB}"
    w = W()
    w.b += b"SPSOHRO1"
    w.pack("I", 1)
    w.pack("f", args.studs)
    w.str(args.hero)
    w.pack("H", len(hero.nodes))
    bone_nodes = set(hero.bones)
    for ni, n in enumerate(hero.nodes):
        w.str(n["name"] if ni in bone_nodes else clean(n["name"]))  # bones must keep the rig's names
        w.pack("h", n["parent"])
        w.f32(n["t"])
        w.f32(n["q"])
        w.f32(n["s"])
    # per-bone radius: furthest vertex weighted to the bone, from the bone's bind origin
    bind_r = np.stack([hero.G @ b @ hero.Gi for b in hero.bind_world])
    radius = np.zeros(NB)
    for p in parts:
        for c in range(4):
            m = p["bw"][:, c] > 1e-3
            if m.any():
                d = np.linalg.norm(p["P"][m] - bind_r[p["bi"][m, c], :3, 3], axis=1)
                np.maximum.at(radius, p["bi"][m, c], d)
    w.pack("H", NB)
    for b in range(NB):
        w.pack("H", hero.bones[b])
        w.f32(hero.binv[b][:3, :4].ravel())
        w.pack("f", radius[b])
    w.pack("H", len(parts))
    mesh_info = []
    for p in parts:
        nV = len(p["P"])
        nmap, nlist, uvmap, uvlist, tris = {}, [], {}, [], []
        cr = p["corners"]
        for t in range(len(cr) // 3):
            tri_v, tri_n, tri_uv = [], [], []
            for c in range(3):
                v = int(cr[3 * t + c]["v"])
                nk = (v,) + tuple(np.round(cr[3 * t + c]["n"].astype(np.float64), 5))
                if nk not in nmap:
                    nmap[nk] = len(nlist)
                    nlist.append((v, cr[3 * t + c]["n"]))
                uk = tuple(np.round(cr[3 * t + c]["uv"].astype(np.float64), 6))
                if uk not in uvmap:
                    uvmap[uk] = len(uvlist)
                    uvlist.append(cr[3 * t + c]["uv"])
                tri_v.append(v)
                tri_n.append(nmap[nk])
                tri_uv.append(uvmap[uk])
            tris.append(tri_v + tri_n + tri_uv)
        w.str(p["name"])
        w.pack("I", nV)
        w.f32(p["P"].ravel())
        w.b += p["bi"].astype(np.uint8).tobytes()
        w.f32(p["bw"].ravel())
        w.pack("I", len(nlist))
        for v, n in nlist:
            w.pack("I", v)
            w.f32(n)
        w.pack("I", len(uvlist))
        w.f32(np.array(uvlist).ravel())
        w.pack("I", len(tris))
        w.b += np.array(tris, "<u4").tobytes()
        mesh_info.append({"name": p["name"], "verts": nV, "normals": len(nlist), "uvs": len(uvlist), "tris": len(tris)})
    w.pack("H", len(hero.clips))
    n_keys = n_const = 0
    for c in hero.clips:
        w.str(c["name"])
        w.pack("f", c["duration"])
        w.pack("f", c["rate"])
        w.pack("B", c["wrap"] & 0xFF)
        w.pack("B", 1 if c["root_motion"] else 0)
        w.pack("H", len(c["events"]))
        for e in c["events"]:
            w.pack("f", e["time"])
            w.str(e["function"])
            w.str(e["data"])
            w.pack("f", e["float"])
            w.pack("i", e["int"])
        w.pack("H", len(c["curves"]))
        for cv in c["curves"]:
            const = len(cv["t"]) == 1 or (np.abs(cv["v"] - cv["v"][:1]).max() == 0 and
                                          not np.any(cv["in"]) and not np.any(cv["out"]))
            n = len(cv["t"])
            frames = np.round(cv["t"] * c["rate"])
            on_grid = (not const and frames.max() < 65536 and
                       np.array_equal((frames / c["rate"]).astype(np.float32), cv["t"].astype(np.float32)))
            fin, fout = cv["in"].astype(np.float32), cv["out"].astype(np.float32)
            diff = np.any(fin != fout, axis=1) & ~(np.isnan(fin).all(1) & np.isnan(fout).all(1))
            flags = (1 if const else 0) | (2 if on_grid else 0) | (4 if (not const and diff.any()) else 0)
            w.pack("H", cv["node"])
            w.pack("B", cv["kind"])
            w.pack("B", flags)
            if const:
                w.f32(cv["v"][0])
                n_const += 1
                continue
            w.pack("H", n)
            if on_grid:
                w.b += frames.astype("<u2").tobytes()
            else:
                w.f32(cv["t"])
            w.f32(cv["v"].ravel())
            w.f32(cv["in"].ravel())
            if flags & 4:
                w.b += np.packbits(diff, bitorder="little").tobytes()
                w.f32(cv["out"][diff].ravel())
            n_keys += n
    # self-test samples: off-grid times included, so the runtime proves exact in-between evaluation
    by_name = {c["name"]: i for i, c in enumerate(hero.clips)}
    picks = []
    scale_dev = {}
    for i, c in enumerate(hero.clips):
        tt = np.linspace(0, c["duration"], max(2, int(c["duration"] * 30)))
        S = hero.skin_mats(c, tt)
        scale_dev[c["name"]] = float(np.abs(np.linalg.svd(S[..., :3, :3], compute_uv=False) - 1).max())
    ranked = sorted(scale_dev, key=lambda n: -scale_dev[n])
    for name in [ranked[0], next((n for n in ranked if scale_dev[n] < 1e-4 and n.startswith("attack")), None),
                 "movement_run" if "movement_run" in by_name else None, ranked[len(ranked) // 2]]:
        if name and name not in picks:
            picks.append(name)
    tests = []
    for name in picks:
        c = hero.clips[by_name[name]]
        d = c["duration"]
        for t in (0.0, 0.1234, d * 0.5 + 0.00777, max(0.0, d - 0.0101), d):
            tests.append((by_name[name], float(np.float32(t))))
    w.pack("H", len(tests))
    for ci, t in tests:
        S = hero.skin_mats(hero.clips[ci], np.float32(t))[0]
        w.pack("H", ci)
        w.pack("f", t)
        w.f32(S[:, :3, :4].ravel())
    w.pack("H", len(hero.clips))
    for ci, c in enumerate(hero.clips):
        t = float(np.float32(c["duration"] * 0.37 + 0.003))
        w.pack("H", ci)
        w.pack("f", t)
        w.pack("d", signature(hero.skin_mats(c, np.float32(t))[0]))
    raw = bytes(w.b)
    z = zstandard.ZstdCompressor(level=19).compress(raw)
    os.makedirs(args.out, exist_ok=True)
    open(os.path.join(args.out, f"{args.hero}.spsohero"), "wb").write(z)
    open(os.path.join(args.out, f"{args.hero}.spsohero.b64"), "w").write(base64.b64encode(z).decode())
    info = {"hero": args.hero, "studsPerUnit": args.studs, "rawBytes": len(raw), "zstdBytes": len(z),
            "nodes": [n["name"] if i in set(hero.bones) else clean(n["name"]) for i, n in enumerate(hero.nodes)], "bones": [hero.nodes[b]["name"] for b in hero.bones],
            "mesh": mesh_info, "curveKeys": n_keys, "constantCurves": n_const, "selfTest": picks,
            "clips": [{"name": c["name"], "duration": round(c["duration"], 6), "rootMotion": c["root_motion"],
                       "maxScaleDeviation": round(scale_dev[c["name"]], 5), "events": c["events"]} for c in hero.clips]}
    # optional: prove the converted curves match the exact extraction at every 60 fps sample
    if args.exact:
        ex = np.load(args.exact + ".npz")
        meta = json.load(open(args.exact + ".json"))
        assert [hero.nodes[b]["name"] for b in hero.bones] == meta["bones"], "bone order differs from exact data"
        worst_m, worst_v = 0.0, 0.0
        for c in hero.clips:
            Wu = ex["clip__" + c["name"]]
            t = ex["times__" + c["name"]]
            Sref = np.einsum("ij,tbjk,bkl,lm->tbim", hero.G, Wu, np.linalg.inv(ex["bind_world"]), hero.Gi)
            S = hero.skin_mats(c, t)
            worst_m = max(worst_m, float(np.abs(S - Sref)[..., :3, :].max()))
            for p in parts:
                Pv = np.c_[p["P"], np.ones(len(p["P"]))]
                for Sx, name in ((S, "pack"), (Sref, "ref")):
                    v = sum(p["bw"][:, j, None] * np.einsum("tvij,vj->tvi", Sx[:, p["bi"][:, j], :3, :], Pv) for j in range(4))
                    if name == "pack":
                        vp = v
                worst_v = max(worst_v, float(np.linalg.norm(vp - v, axis=-1).max()))
        info["checkVsExact"] = {"maxMatrixError": worst_m, "maxVertexErrorStuds": worst_v}
        print(f"check vs exact extraction: matrix {worst_m:.2e}, vertex {worst_v:.2e} studs")
    json.dump(info, open(os.path.join(args.out, f"{args.hero}.pack.json"), "w"), indent=1)
    print(f"{args.hero}: {len(hero.nodes)} nodes, {NB} bones, {len(hero.clips)} clips, {n_keys} keys "
          f"({n_const} constant curves), mesh {mesh_info}; raw {len(raw)/1e6:.2f} MB -> zstd {len(z)/1e6:.2f} MB; "
          f"self-test clips {picks}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("mesh")
    ap.add_argument("hero")
    ap.add_argument("out")
    ap.add_argument("--studs", type=float, default=2.56)
    ap.add_argument("--exact", default=None)
    build(ap.parse_args())
