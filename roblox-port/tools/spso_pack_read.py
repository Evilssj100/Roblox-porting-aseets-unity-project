"""Reference reader + evaluator for SPSOHRO1 hero packs (see spso_hero_pack.py for the format).
The Roblox runtime (roblox/SPSO/HeroPack.lua + ExactAnimator.lua) mirrors this code.

Usage: python spso_pack_read.py <Hero.spsohero>      decodes, re-evaluates the self-tests and every clip
                                                      signature, prints the worst errors.
"""
import struct
import sys

import numpy as np
import zstandard

DIM = (4, 3, 3)


class R:
    def __init__(self, b):
        self.b, self.o = b, 0

    def u(self, fmt):
        v = struct.unpack_from("<" + fmt, self.b, self.o)
        self.o += struct.calcsize("<" + fmt)
        return v if len(v) > 1 else v[0]

    def s(self):
        n = self.u("H")
        v = self.b[self.o:self.o + n].decode()
        self.o += n
        return v

    def arr(self, dtype, n):
        a = np.frombuffer(self.b, dtype, n, self.o)
        self.o += a.nbytes
        return a


def read_pack(path):
    raw = open(path, "rb").read()
    if raw[:8] != b"SPSOHRO1":
        raw = zstandard.ZstdDecompressor().decompress(raw, max_output_size=1 << 30)
    r = R(raw)
    assert r.b[:8] == b"SPSOHRO1"
    r.o = 8
    p = {"version": r.u("I"), "studs": r.u("f"), "hero": r.s(), "nodes": [], "bones": [], "parts": [], "clips": []}
    for _ in range(r.u("H")):
        p["nodes"].append({"name": r.s(), "parent": r.u("h"), "t": r.arr("<f4", 3), "q": r.arr("<f4", 4), "s": r.arr("<f4", 3)})
    for _ in range(r.u("H")):
        p["bones"].append({"node": r.u("H"), "binv": r.arr("<f4", 12).reshape(3, 4), "radius": r.u("f")})
    for _ in range(r.u("H")):
        part = {"name": r.s()}
        nV = r.u("I")
        part["pos"] = r.arr("<f4", nV * 3).reshape(nV, 3)
        part["bi"] = r.arr("u1", nV * 4).reshape(nV, 4)
        part["bw"] = r.arr("<f4", nV * 4).reshape(nV, 4)
        nN = r.u("I")
        nrm = r.arr(np.dtype([("v", "<u4"), ("n", "<f4", 3)]), nN)
        part["nvert"], part["normals"] = nrm["v"], nrm["n"]
        part["uvs"] = r.arr("<f4", r.u("I") * 2).reshape(-1, 2)
        part["tris"] = r.arr("<u4", r.u("I") * 9).reshape(-1, 9)
        p["parts"].append(part)
    for _ in range(r.u("H")):
        c = {"name": r.s(), "duration": r.u("f"), "rate": r.u("f"), "wrap": r.u("B"), "flags": r.u("B"),
             "events": [], "curves": []}
        for _ in range(r.u("H")):
            c["events"].append({"time": r.u("f"), "function": r.s(), "data": r.s(), "float": r.u("f"), "int": r.u("i")})
        for _ in range(r.u("H")):
            node, kind, flags = r.u("H"), r.u("B"), r.u("B")
            d = DIM[kind]
            cv = {"node": node, "kind": kind}
            if flags & 1:
                cv["const"] = r.arr("<f4", d).astype(np.float64)
            else:
                n = r.u("H")
                if flags & 2:
                    cv["t"] = (r.arr("<u2", n) / np.float64(c["rate"])).astype(np.float32).astype(np.float64)
                else:
                    cv["t"] = r.arr("<f4", n).astype(np.float64)
                cv["v"] = r.arr("<f4", n * d).reshape(n, d).astype(np.float64)
                cv["in"] = r.arr("<f4", n * d).reshape(n, d).astype(np.float64)
                out = cv["in"].copy()
                if flags & 4:
                    mask = np.unpackbits(r.arr("u1", (n + 7) // 8), bitorder="little")[:n].astype(bool)
                    out[mask] = r.arr("<f4", int(mask.sum()) * d).reshape(-1, d)
                cv["out"] = out
            c["curves"].append(cv)
        p["clips"].append(c)
    p["tests"] = []
    for _ in range(r.u("H")):
        p["tests"].append({"clip": r.u("H"), "time": r.u("f"), "S": r.arr("<f4", len(p["bones"]) * 12).reshape(-1, 3, 4)})
    p["sigs"] = []
    for _ in range(r.u("H")):
        p["sigs"].append({"clip": r.u("H"), "time": r.u("f"), "sig": r.u("d")})
    assert r.o == len(raw), f"trailing bytes: {len(raw) - r.o}"
    return p


def hermite1(cv, t):
    """single-time Unity curve evaluation (what the runtime does per frame)"""
    if "const" in cv:
        return cv["const"]
    kt = cv["t"]
    n = len(kt)
    if n == 1 or t <= kt[0]:
        return cv["v"][0]
    if t >= kt[-1]:
        return cv["v"][-1]
    i = int(np.searchsorted(kt, t, side="right")) - 1
    i = min(max(i, 0), n - 2)
    dt = kt[i + 1] - kt[i]
    if dt <= 0:
        return cv["v"][i]
    u = (t - kt[i]) / dt
    m0 = cv["out"][i] * dt
    m1 = cv["in"][i + 1] * dt
    u2, u3 = u * u, u * u * u
    with np.errstate(all="ignore"):
        r = (2 * u3 - 3 * u2 + 1) * cv["v"][i] + (u3 - 2 * u2 + u) * m0 + (-2 * u3 + 3 * u2) * cv["v"][i + 1] + (u3 - u2) * m1
    bad = ~np.isfinite(m0) | ~np.isfinite(m1) | ~np.isfinite(r)
    return np.where(bad, cv["v"][i], r)


def skin_mats(p, ci, t):
    """skinning matrices (nBones, 3, 4) of clip ci at time t, from decoded pack data"""
    N = len(p["nodes"])
    loc = [[n["t"].astype(np.float64), n["q"].astype(np.float64), n["s"].astype(np.float64)] for n in p["nodes"]]
    for cv in p["clips"][ci]["curves"]:
        loc[cv["node"]][(1, 0, 2)[cv["kind"]]] = np.asarray(hermite1(cv, t), np.float64)
    W = [None] * N
    for i, n in enumerate(p["nodes"]):
        t3, q, s = loc[i]
        q = q / max(np.linalg.norm(q), 1e-12)
        x, y, z, w = q
        R3 = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                       [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                       [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        L = np.eye(4)
        L[:3, :3] = R3 * s[None, :]
        L[:3, 3] = t3
        W[i] = L if n["parent"] < 0 else W[n["parent"]] @ L
    out = np.zeros((len(p["bones"]), 3, 4))
    for b, bone in enumerate(p["bones"]):
        Bi = np.eye(4)
        Bi[:3, :] = bone["binv"]
        out[b] = (W[bone["node"]] @ Bi)[:3, :]
    return out


def signature(S):
    wgt = np.arange(1, len(S) + 1)[:, None, None] * np.arange(1, 13).reshape(1, 3, 4)
    return float((S * wgt).sum())


if __name__ == "__main__":
    p = read_pack(sys.argv[1])
    te = max(float(np.abs(skin_mats(p, x["clip"], x["time"]) - x["S"]).max()) for x in p["tests"])
    se = max(abs(signature(skin_mats(p, x["clip"], x["time"])) - x["sig"]) / max(1.0, abs(x["sig"])) for x in p["sigs"])
    print(f"{p['hero']}: {len(p['nodes'])} nodes, {len(p['bones'])} bones, {len(p['clips'])} clips, "
          f"{len(p['parts'])} parts; self-test max |dS| {te:.2e}; worst signature rel. error {se:.2e}")
