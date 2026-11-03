"""Convert a Unity 3.x text-serialized environment bundle (.asset YAML) into a GLB for Blender/Roblox.

What it handles (SHSO environment style):
  * hierarchy (Transforms), MeshFilter + Renderer meshes, MeshCollider meshes (exported as
    "<name>_collision" nodes with extras.collision = true)
  * "Marvel/Lightmap/Vertex Color" materials: final colour = vertex colour x lightmap(uv1) x 2.
    That product is baked into ONE texture per material on uv1, and uv1 becomes TEXCOORD_0, so
    every visible part ends up with a single texture and a single UV set (what Roblox wants).
  * "Marvel/Base/Self-Illuminated" materials: vertex colour baked the same way, marked emissive.
  * other materials with a _MainTex: that texture on uv0.
  * transform AnimationClips on Animation components (Hermite-evaluated, 30 fps).
Unity is left-handed: X is mirrored and winding flipped, as in unity_hero_to_glb.py.

Usage: python unity_yaml_scene_to_glb.py <bundle.asset> <out_dir> [--lm-gain 1.5]
"""
import io
import json
import os
import re
import sys

import numpy as np
import texture2ddecoder
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unity_yaml as uy  # noqa: E402
from unity_hero_to_glb import GLB, eval_curve, mirror_quat, mirror_pos  # noqa: E402

FPS = 30.0
CH_SIZE = [12, 12, 4, 8, 8, 16]  # Unity 3.x: vertex, normal, color, uv0, uv1, tangent


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("_") or "unnamed"


# ------------------------------------------------------------------ decoding
def decode_mesh(o):
    vd = o["m_VertexData"]
    n = int(vd["m_VertexCount"])
    raw = uy.hexbytes(o, vd.get("_typelessdata"))
    chans = {}
    for k in range(4):
        st = vd.get(f"m_Streams[{k}]")
        if not st or not int(st["channelMask"]):
            continue
        mask, off, stride = int(st["channelMask"]), int(st["offset"]), int(st["stride"])
        coff = 0
        for c in range(6):
            if mask & (1 << c):
                if c == 2:
                    dt, dim = np.uint8, 4
                else:
                    dt, dim = np.float32, CH_SIZE[c] // 4
                buf = np.frombuffer(raw, dtype=np.uint8, count=n * stride, offset=off).reshape(n, stride)
                chans[c] = buf[:, coff:coff + CH_SIZE[c]].copy().view(dt).reshape(n, dim)
                coff += CH_SIZE[c]
    ib = np.frombuffer(uy.hexbytes(o, o.get("m_IndexBuffer")), dtype=np.uint16).astype(np.int64)
    subs = []
    for sm in o["m_SubMeshes"]:
        first = int(sm["firstByte"]) // 2
        idx = ib[first:first + int(sm["indexCount"])]
        if int(sm.get("isTriStrip", 0) or 0):
            tris = []
            for i in range(len(idx) - 2):
                a, b, c = idx[i], idx[i + 1], idx[i + 2]
                if a != b and b != c and a != c:
                    tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
            subs.append(np.array(tris, dtype=np.int64).reshape(-1, 3))
        else:
            subs.append(idx[: len(idx) // 3 * 3].reshape(-1, 3))
    return chans, subs


def decode_texture(o):
    w, h, fmt = int(o["m_Width"]), int(o["m_Height"]), int(o["m_TextureFormat"])
    raw = uy.hexbytes(o, o.get("_typelessdata"))
    if fmt == 10:  # DXT1
        px = texture2ddecoder.decode_bc1(raw[: w * h // 2], w, h)
        im = Image.frombytes("RGBA", (w, h), px, "raw", "BGRA")
    elif fmt == 12:  # DXT5
        px = texture2ddecoder.decode_bc3(raw[: w * h], w, h)
        im = Image.frombytes("RGBA", (w, h), px, "raw", "BGRA")
    elif fmt == 4:
        im = Image.frombytes("RGBA", (w, h), raw[: w * h * 4])
    elif fmt == 5:  # ARGB32
        a = np.frombuffer(raw[: w * h * 4], np.uint8).reshape(h, w, 4)[..., [1, 2, 3, 0]]
        im = Image.fromarray(a, "RGBA")
    elif fmt == 3:
        im = Image.frombytes("RGB", (w, h), raw[: w * h * 3]).convert("RGBA")
    elif fmt == 1:
        a = np.frombuffer(raw[: w * h], np.uint8).reshape(h, w)
        im = Image.fromarray(np.dstack([np.full_like(a, 255)] * 3 + [a]), "RGBA")
    else:
        raise ValueError(f"texture format {fmt} not handled")
    return im.transpose(Image.FLIP_TOP_BOTTOM)  # Unity stores bottom row first


# ------------------------------------------------------------------ baking
def bake_vertex_colour(uv, tris, vcol, res, lm=None, gain=2.0):
    """Rasterise per-vertex colour over `uv` (Unity convention, v up) at res x res,
    optionally multiplied by lightmap image `lm` (same UVs) x gain. Returns (RGB uint8 image, coverage)."""
    H = W = res
    acc = np.zeros((H, W, 3), np.float32)
    cov = np.zeros((H, W), bool)
    P = np.stack([uv[:, 0] * W, (1.0 - uv[:, 1]) * H], axis=1)
    for t in tris:
        a, b, c = P[t]
        x0, y0 = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        x1, y1 = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W - 1), min(y1, H - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        l0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / den
        l1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / den
        l2 = 1 - l0 - l1
        tol = -0.02
        inside = (l0 >= tol) & (l1 >= tol) & (l2 >= tol)
        if not inside.any():
            continue
        Lm = np.clip(np.stack([l0[inside], l1[inside], l2[inside]], 1), 0, None)
        Lm /= Lm.sum(1, keepdims=True)
        yy, xx = (ys[inside] - 0.5).astype(int), (xs[inside] - 0.5).astype(int)
        acc[yy, xx] = Lm @ vcol[t]
        cov[yy, xx] = True
    if lm is not None:
        # SHSO "Lightmap/Vertex Color": albedo = vertex colour x lightmap.a (AO); lightmap.rgb is an
        # extra baked light term added on top of real-time lighting. Keep a share of it as glow.
        lmr = np.asarray(lm.convert("RGBA").resize((W, H), Image.BILINEAR)).astype(np.float32) / 255
        acc = acc * lmr[..., 3:4] * (1.0 + gain * lmr[..., :3])
    dist, (iy, ix) = ndi.distance_transform_edt(~cov, return_indices=True)
    acc = acc[iy, ix]
    return Image.fromarray((np.clip(acc, 0, 1) * 255 + 0.5).astype(np.uint8)), cov


# ------------------------------------------------------------------ main
def convert(path, out_dir, gain=2.0):
    os.makedirs(os.path.join(out_dir, "textures"), exist_ok=True)
    objs = uy.load(path)
    by_cls = {}
    for o in objs.values():
        by_cls.setdefault(o.cls, []).append(o)
    shaders = {o.fid: o.get("m_Name", "") for o in by_cls.get("Shader", [])}

    tex_img = {}
    for o in by_cls.get("Texture2D", []):
        try:
            im = decode_texture(o)
            tex_img[o.fid] = im
            im.save(os.path.join(out_dir, "textures", safe(o["m_Name"]) + ".png"))
        except Exception as e:
            print("texture failed", o["m_Name"], e)

    comps = {}
    for cls in ("Transform", "MeshFilter", "Renderer", "MeshCollider", "Animation"):
        for o in by_cls.get(cls, []):
            comps.setdefault(uy.ref(o["m_GameObject"]), {})[cls] = o
    tr_of = {go: c["Transform"] for go, c in comps.items() if "Transform" in c}
    go_of_tr = {t.fid: go for go, t in tr_of.items()}

    g = GLB()
    g.j["scenes"] = [{"nodes": []}]
    g.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071})
    node_of_tr, path_of_node = {}, {}
    meta = {"source": os.path.basename(path), "objects": [], "materials": {}, "animations": []}
    mesh_cache = {}

    def add_image(img, name):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        g.j["images"].append({"name": name, "mimeType": "image/png", "bufferView": g.view(buf.getvalue())})
        g.j["textures"].append({"sampler": 0, "source": len(g.j["images"]) - 1})
        return len(g.j["textures"]) - 1

    def build_mesh(go_name, mesh_obj, mats):
        chans, subs = decode_mesh(mesh_obj)
        V = chans[0].astype(np.float64).copy()
        V[:, 0] *= -1
        uv0 = chans.get(3)
        uv1 = chans.get(4)
        vcol = chans[2][:, [0, 1, 2]].astype(np.float32) / 255 if 2 in chans else np.ones((len(V), 3), np.float32)
        attrs = {"POSITION": g.acc(V.astype(np.float32), "VEC3", 5126, 34962, minmax=True)}
        if 1 in chans:
            Nn = chans[1].astype(np.float64).copy()
            Nn[:, 0] *= -1
            Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
            attrs["NORMAL"] = g.acc(Nn.astype(np.float32), "VEC3", 5126, 34962)
        prim_uv = uv1 if uv1 is not None else uv0
        if prim_uv is not None:
            T0 = prim_uv.astype(np.float64).copy()
            T0[:, 1] = 1 - T0[:, 1]
            attrs["TEXCOORD_0"] = g.acc(T0.astype(np.float32), "VEC2", 5126, 34962)
        if uv0 is not None and uv1 is not None:
            T1 = uv0.astype(np.float64).copy()
            T1[:, 1] = 1 - T1[:, 1]
            attrs["TEXCOORD_1"] = g.acc(T1.astype(np.float32), "VEC2", 5126, 34962)
        attrs["COLOR_0"] = g.acc(vcol, "VEC3", 5126, 34962)
        prims = []
        for k, tris in enumerate(subs):
            if not len(tris):
                continue
            mat = mats[min(k, len(mats) - 1)] if mats else None
            mi = None
            if mat is not None:
                key = (mat.fid, mesh_obj.fid, k)
                sh = shaders.get(uy.ref(mat["m_Shader"]), "")
                envs = uy.tex_envs(mat)
                entry = {"name": mat["m_Name"], "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0},
                         "extras": {"unity_shader": sh}}
                lm_id = envs.get("_LightMap", (0,))[0]
                main_id = envs.get("_MainTex", (0,))[0]
                res = 0
                if sh == "LightMap-VC" and prim_uv is not None:
                    lm = tex_img.get(lm_id)
                    res = max(256, lm.size[0] if lm else 256)
                    img, _ = bake_vertex_colour(prim_uv, tris, vcol, res, lm, gain)
                    fn = f"{safe(go_name)}__{k}_baked.png"
                    img.save(os.path.join(out_dir, "textures", fn))
                    entry["pbrMetallicRoughness"]["baseColorTexture"] = {"index": add_image(img, fn)}
                elif sh == "Self-Illum":
                    c = vcol[np.unique(tris)].mean(axis=0)
                    entry["pbrMetallicRoughness"]["baseColorFactor"] = [*map(float, c), 1.0]
                    entry["emissiveFactor"] = [float(x) for x in c]
                    entry["extras"]["glow"] = True
                elif main_id and main_id in tex_img:
                    fn = f"{safe(objs[main_id]['m_Name'])}.png"
                    entry["pbrMetallicRoughness"]["baseColorTexture"] = {"index": add_image(tex_img[main_id], fn),
                                                                         "texCoord": 1 if "TEXCOORD_1" in attrs else 0}
                    if tex_img[main_id].mode == "RGBA" and np.asarray(tex_img[main_id])[..., 3].min() < 250:
                        entry["alphaMode"] = "BLEND"
                g.j["materials"].append(entry)
                mi = len(g.j["materials"]) - 1
                meta["materials"][mat["m_Name"]] = {"shader": sh, "baked_res": res,
                                                    "textures": {k2: objs[v[0]]["m_Name"] for k2, v in envs.items() if v[0] in objs}}
            fl = tris[:, [0, 2, 1]].reshape(-1)
            big = len(V) > 65535
            prim = {"attributes": attrs, "indices": g.acc(fl.astype(np.uint32 if big else np.uint16), "SCALAR",
                                                          5125 if big else 5123, 34963)}
            if mi is not None:
                prim["material"] = mi
            prims.append(prim)
        g.j["meshes"].append({"name": mesh_obj["m_Name"], "primitives": prims})
        return len(g.j["meshes"]) - 1, len(V), sum(len(t) for t in subs)

    def collision_material():
        if "_collision_mat" not in mesh_cache:
            g.j["materials"].append({"name": "collision", "alphaMode": "BLEND",
                                     "pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.9, 0.4, 0.25]}})
            mesh_cache["_collision_mat"] = len(g.j["materials"]) - 1
        return mesh_cache["_collision_mat"]

    def walk(tr, parent_path):
        go = objs[uy.ref(tr["m_GameObject"])]
        name = go["m_Name"]
        p = f"{parent_path}/{name}" if parent_path else name
        i = len(g.j["nodes"])
        node = {"name": name}
        t = mirror_pos([float(tr["m_LocalPosition"][k]) for k in "xyz"])
        r = mirror_quat([float(tr["m_LocalRotation"][k]) for k in "xyzw"])
        s = [float(tr["m_LocalScale"][k]) for k in "xyz"]
        if not np.allclose(t, 0):
            node["translation"] = t
        if not np.allclose(r, [0, 0, 0, 1]):
            node["rotation"] = r
        if not np.allclose(s, 1):
            node["scale"] = s
        g.j["nodes"].append(node)
        node_of_tr[tr.fid] = i
        path_of_node[i] = p
        c = comps.get(go.fid, {})
        info = {"name": name, "path": p}
        if "MeshFilter" in c and "Renderer" in c:
            mo = objs.get(uy.ref(c["MeshFilter"]["m_Mesh"]))
            if mo is not None:
                mats = [objs.get(uy.ref(m)) for m in c["Renderer"]["m_Materials"]]
                mats = [m for m in mats if m is not None]
                mi, nv, nt = build_mesh(name, mo, mats)
                node["mesh"] = mi
                info.update({"mesh": mo["m_Name"], "verts": nv, "tris": nt, "materials": [m["m_Name"] for m in mats]})
        if "MeshCollider" in c:
            mo = objs.get(uy.ref(c["MeshCollider"]["m_Mesh"]))
            if mo is not None:
                chans, subs = decode_mesh(mo)
                V = chans[0].astype(np.float64).copy()
                V[:, 0] *= -1
                tris = np.concatenate(subs)[:, [0, 2, 1]].reshape(-1)
                prim = {"attributes": {"POSITION": g.acc(V.astype(np.float32), "VEC3", 5126, 34962, minmax=True)},
                        "indices": g.acc(tris.astype(np.uint32), "SCALAR", 5125, 34963),
                        "material": collision_material()}
                g.j["meshes"].append({"name": mo["m_Name"] + "_collision", "primitives": [prim]})
                cn = {"name": name + "_collision", "mesh": len(g.j["meshes"]) - 1, "extras": {"collision": True}}
                g.j["nodes"].append(cn)
                node.setdefault("children", []).append(len(g.j["nodes"]) - 1)
                info["collision"] = mo["m_Name"]
        meta["objects"].append(info)
        kids = []
        for ch in tr.get("m_Children", []) or []:
            ctr = objs.get(uy.ref(ch))
            if ctr is not None:
                kids.append(walk(ctr, p))
        if kids:
            node.setdefault("children", []).extend(kids)
        return i

    roots = [t for t in by_cls.get("Transform", []) if uy.ref(t.get("m_Father")) == 0]
    for t in roots:
        g.j["scenes"][0]["nodes"].append(walk(t, ""))

    # animations
    for an in by_cls.get("Animation", []):
        go = objs[uy.ref(an["m_GameObject"])]
        base_node = node_of_tr[tr_of[go.fid].fid]
        base_path = path_of_node[base_node]
        clips = [objs.get(uy.ref(c)) for c in an.get("m_Animations", []) or []]
        for clip in [c for c in clips if c is not None]:
            dur = 0.0
            groups = [("rotation", clip.get("m_RotationCurves", []) or [], 4),
                      ("translation", clip.get("m_PositionCurves", []) or [], 3),
                      ("scale", clip.get("m_ScaleCurves", []) or [], 3)]
            for _, cs, _ in groups:
                for c in cs:
                    keys = c["curve"]["m_Curve"]
                    if keys:
                        dur = max(dur, float(keys[-1]["time"]))
            times = np.arange(0.0, dur + 1e-9, 1.0 / FPS)
            if times[-1] < dur - 1e-6:
                times = np.append(times, dur)
            a = {"name": f"{go['m_Name']}__{clip['m_Name']}", "samplers": [], "channels": []}
            tin = g.acc(times.astype(np.float32), "SCALAR", 5126, minmax=True)
            for prop, cs, dim in groups:
                for c in cs:
                    target = base_path + "/" + c["path"] if c["path"] else base_path
                    n = next((k for k, v in path_of_node.items() if v == target), None)
                    if n is None:
                        continue

                    class K:  # adapt YAML keys to eval_curve's attribute access
                        def __init__(self, d):
                            self.time = float(d["time"])
                            self.value = [float(d["value"][q]) for q in "xyzw"[:dim]]
                            self.inSlope = [float(d["inSlope"][q]) for q in "xyzw"[:dim]]
                            self.outSlope = [float(d["outSlope"][q]) for q in "xyzw"[:dim]]

                    vals = eval_curve([K(d) for d in c["curve"]["m_Curve"]], times, dim)
                    if prop == "rotation":
                        vals = np.stack([vals[:, 0], -vals[:, 1], -vals[:, 2], vals[:, 3]], 1)
                        vals /= np.maximum(np.linalg.norm(vals, axis=1, keepdims=True), 1e-9)
                        for f in range(1, len(vals)):
                            if np.dot(vals[f], vals[f - 1]) < 0:
                                vals[f] = -vals[f]
                    elif prop == "translation":
                        vals[:, 0] *= -1
                    out = g.acc(vals.astype(np.float32), "VEC4" if dim == 4 else "VEC3", 5126)
                    a["samplers"].append({"input": tin, "output": out, "interpolation": "LINEAR"})
                    a["channels"].append({"sampler": len(a["samplers"]) - 1, "target": {"node": n, "path": prop}})
            if a["channels"]:
                g.j["animations"].append(a)
                meta["animations"].append({"name": a["name"], "duration": round(dur, 3), "channels": len(a["channels"]),
                                           "loop": int(an.get("m_WrapMode", 0) or 0)})

    if "extensionsUsed" in g.j:
        g.j["extensionsUsed"] = sorted(set(g.j["extensionsUsed"]))
    name = safe(os.path.splitext(os.path.basename(path))[0])
    g.write(os.path.join(out_dir, f"{name}.glb"))
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)
    vis = [o for o in meta["objects"] if "mesh" in o]
    print(f"{name}: nodes={len(g.j['nodes'])} visible meshes={len(vis)} verts={sum(o['verts'] for o in vis)} "
          f"tris={sum(o['tris'] for o in vis)} collision={sum(1 for o in meta['objects'] if 'collision' in o)} "
          f"animations={len(meta['animations'])} textures={len(tex_img)}")


if __name__ == "__main__":
    gain = 1.5
    if "--lm-gain" in sys.argv:
        gain = float(sys.argv[sys.argv.index("--lm-gain") + 1])
    convert(sys.argv[1], sys.argv[2], gain)
