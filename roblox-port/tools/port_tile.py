"""Port an original brawler tile or prop (a GameObject subtree of an SHSO archive bundle) to a Roblox-ready
FBX, built straight in (cloud) Blender from the bundle data:

* every renderer of the subtree, in the subtree root's space (the root itself at the origin, like the
  game's ObjectPlaceholder does when it instantiates a tile)
* "LightMap-VC" / vertex colour materials: vertex colour x lightmap baked into ONE texture per renderer on
  the lightmap UVs (one MeshPart, one TextureID); "Self-Illum" materials become separate glow parts (Neon,
  mean vertex colour); textured materials (_MainTex, tiling applied) become their own parts
* units: studs (k = 2.56 per unit); axes: Roblox local = (x, y, -z) of the Unity root space. FBX objects
  carry identity transforms, so each imported MeshPart sits at its bounding-box centre (listed in the JSON)
* collision: MeshCollider triangles (Roblox local studs, outward winding) and BoxColliders, for the
  runtime to rebuild as wedges/boxes (concave meshes can't be MeshPart collision)
* --mirror writes the mirrored variant (Unity local x -> -x) that mirrored placements need
* writes <out>/<Name>.fbx, <Name>.json, <Name>_preview.png, textures/*.png

Usage: python port_tile.py <bundle.asset> <root GameObject name> <out_dir> [--name Name] [--mirror] [--lm-gain 1.5]
       [--no-preview] [--skip REGEX]
"""
import argparse
import json
import os
import re
import sys

import bpy  # noqa: F401  (load before mathutils in the pip build)
import numpy as np
from mathutils import Vector
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spso_names import check, clean  # noqa: E402
from unity_bundle_tree import Bundle  # noqa: E402
from unity_yaml_scene_to_glb import bake_vertex_colour  # noqa: E402

K = 2.56


def cap(s):
    return s[:1].upper() + s[1:]


BAKED = {"LightMap-VC", "VertexColor", "Lightmap/VertexColor", "VertexLit-VC", "AO-VC"}
GLOW = {"Self-Illum"}


def trs(t):
    p, q, s = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * np.array([s["x"], s["y"], s["z"]])
    m[:3, 3] = [p["x"], p["y"], p["z"]]
    return m


def strip_to_tris(idx):
    out = []
    for i in range(len(idx) - 2):
        a, b, c = int(idx[i]), int(idx[i + 1]), int(idx[i + 2])
        if a == b or b == c or a == c:
            continue
        out.append((b, a, c) if i & 1 else (a, b, c))
    return np.array(out, np.int64).reshape(-1, 3)


def read_mesh(tt):
    """Unity 3.x mesh typetree -> positions, normals, uv0, uv1, colours (0-1), submesh triangle lists"""
    def arr(key, comps):
        a = tt.get(key) or []
        return np.array([[v[c] for c in comps] for v in a], np.float64) if a else None
    V = arr("m_Vertices", "xyz")
    if V is None:
        raise ValueError("mesh without m_Vertices (newer vertex-data layout not supported here)")
    N = arr("m_Normals", "xyz")
    uv0 = arr("m_UV", "xy")
    uv1 = arr("m_UV1", "xy")
    cols = tt.get("m_Colors") or []
    if cols:
        c = np.array([v["rgba"] if isinstance(v, dict) else v for v in cols], np.uint32)
        C = np.stack([(c >> s) & 0xFF for s in (0, 8, 16, 24)], 1).astype(np.float32) / 255
    else:
        C = np.ones((len(V), 4), np.float32)
    w = 2 if int(tt.get("m_Use16BitIndices", 1)) else 4
    ib = np.frombuffer(bytes(tt["m_IndexBuffer"]), np.uint16 if w == 2 else np.uint32)
    subs = []
    for sm in tt.get("m_SubMeshes") or []:
        first, cnt = sm["firstByte"] // w, sm["indexCount"]
        idx = ib[first:first + cnt]
        strip = sm.get("isTriStrip", 0)
        if strip == 1 or strip == 2 or (strip and cnt % 3):
            tris = strip_to_tris(idx)
        else:
            tris = idx.astype(np.int64).reshape(-1, 3)
        subs.append(tris)
    return {"V": V, "N": N, "uv0": uv0, "uv1": uv1, "C": C, "subs": subs}


class Tile:
    def __init__(self, bundle_path, root_name):
        self.b = Bundle(bundle_path)
        roots = [g for g in self.b.tr_of_go if self.b.name(g) == root_name]
        if not roots:
            raise SystemExit(f"no GameObject named {root_name}")
        # prefer a top-level object (tiles are bundle roots)
        roots.sort(key=lambda g: len(self.b.path(g)))
        self.root = roots[0]
        self.images = {}

    def image(self, pid):
        if pid not in self.images and not isinstance(pid, tuple):
            o = self.b.objs.get(pid)
            self.images[pid] = o.read().image.convert("RGBA") if o is not None else None
        return self.images[pid]

    def material(self, pid):
        b = self.b
        d = b.read(pid)
        sh = d["m_Shader"]
        shader = ""
        if sh.get("m_PathID") and not sh.get("m_FileID") and sh["m_PathID"] in b.objs:
            shader = b.read(sh["m_PathID"]).get("m_Name", "")
        props = d.get("m_SavedProperties", {})
        tex = {}
        for it in props.get("m_TexEnvs", []):
            name, sec = (it[0]["name"], it[1]) if isinstance(it, (list, tuple)) else (it["first"]["name"], it["second"])
            t = sec.get("m_Texture", {})
            if t.get("m_PathID") and not t.get("m_FileID"):
                tex[name] = (t["m_PathID"], (sec["m_Scale"]["x"], sec["m_Scale"]["y"]), (sec["m_Offset"]["x"], sec["m_Offset"]["y"]))
        colors = {}
        for it in props.get("m_Colors", []):
            name, c = (it[0]["name"], it[1]) if isinstance(it, (list, tuple)) else (it["first"]["name"], it["second"])
            colors[name] = (c["r"], c["g"], c["b"], c["a"])
        return {"name": d["m_Name"], "shader": shader, "tex": tex, "colors": colors}

    def walk(self):
        """(GameObject, matrix relative to the root) for the whole subtree; the root is the origin"""
        stack = [(self.root, np.eye(4))]
        while stack:
            g, m = stack.pop()
            yield g, m
            for k in self.b.children.get(g, []):
                stack.append((k, m @ trs(self.b.read(self.b.tr_of_go[k]))))


def u2r(P):
    """Unity root space -> Roblox local studs"""
    return np.stack([P[:, 0], P[:, 1], -P[:, 2]], 1) * K


def u2b(P):
    """Unity root space -> Blender (the FBX export + Roblox import turn Blender (X,Y,Z) into Roblox (-X,Z,Y))"""
    return np.stack([-P[:, 0], -P[:, 2], P[:, 1]], 1) * K


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--name", default=None)
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--lm-gain", type=float, default=1.5)
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--skip", default=None, help="regex of object names to leave out")
    ap.add_argument("--max-scale", type=float, default=1.0,
                    help="largest placement scale: meshes are split so no part exceeds 2000 studs when scaled")
    a = ap.parse_args()

    name = a.name or cap(clean(a.root))
    if a.mirror:
        name += "_M"
    os.makedirs(os.path.join(a.out, "textures"), exist_ok=True)
    tile = Tile(a.bundle, a.root)
    b = tile.b
    mirror = np.diag([-1.0, 1, 1, 1]) if a.mirror else np.eye(4)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    parts, collision, boxes, skipped = [], [], [], []
    used_names = set()

    def unique(n):
        n = cap(re.sub(r"[^A-Za-z0-9_]", "_", clean(n)))
        base, i = n, 2
        while n in used_names:
            n = f"{base}_{i}"
            i += 1
        used_names.add(n)
        return n

    def add_object(oname, P, tris, uv, img_path, kind, color=None, alpha=False):
        """P: Unity root-space positions of the used vertices; tris index into P (Unity winding)"""
        ext = np.ptp(P[np.unique(tris)], axis=0) * K * a.max_scale
        if ext.max() > 2000 and len(tris) > 1:  # Roblox parts stop at 2048 studs: split along the longest axis
            ax = int(np.argmax(ext))
            cen = P[tris].mean(1)[:, ax]
            cut = np.median(cen)
            lo, hi = tris[cen <= cut], tris[cen > cut]
            if len(lo) and len(hi):
                add_object(oname + "_a", P, lo, uv, img_path, kind, color, alpha)
                add_object(oname + "_b", P, hi, uv, img_path, kind, color, alpha)
                return
        used = np.unique(tris)
        remap = -np.ones(len(P), np.int64)
        remap[used] = np.arange(len(used))
        Pu = P[used]
        T = remap[tris]
        # Unity -> Blender is a reflection: flip winding; the mirror variant flips it back
        T = T[:, [0, 2, 1]] if not a.mirror else T
        me = bpy.data.meshes.new(oname)
        me.from_pydata([tuple(v) for v in u2b(Pu)], [], [tuple(t) for t in T])
        me.update()
        uvl = me.uv_layers.new(name="UVMap")
        if uv is not None:
            uvu = uv[used]
            loops = np.array([l.vertex_index for l in me.loops])
            uvl.data.foreach_set("uv", uvu[loops].astype(np.float32).ravel())
        mat = bpy.data.materials.new(oname)
        mat.use_nodes = True
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        if img_path:
            im = bpy.data.images.load(img_path)
            im.name = os.path.splitext(os.path.basename(img_path))[0]
            im.pack()
            tn = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tn.image = im
            mat.node_tree.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
        elif color is not None:
            bsdf.inputs["Base Color"].default_value = (*color[:3], 1.0)
        me.materials.append(mat)
        ob = bpy.data.objects.new(oname, me)
        scene.collection.objects.link(ob)
        R = u2r(Pu)
        lo, hi = R.min(0), R.max(0)
        parts.append({"name": oname, "kind": kind, "center": ((lo + hi) / 2).round(4).tolist(),
                      "size": (hi - lo).round(4).tolist(), "tris": int(len(T)),
                      **({"color": [round(float(c), 4) for c in color[:3]]} if color is not None else {}),
                      **({"alpha": True} if alpha else {})})

    for g, m in tile.walk():
        gname = b.name(g)
        if a.skip and re.search(a.skip, gname):
            skipped.append(gname)
            continue
        M = mirror @ m
        mf = b.comp(g, "MeshFilter")
        mr = b.comp(g, "MeshRenderer")
        mc = b.comp(g, "MeshCollider")
        bc = b.comp(g, "BoxCollider")
        if mc is not None:
            ref = b.read(mc)["m_Mesh"]
            if ref.get("m_PathID") in b.objs:  # always the un-mirrored tile: the runtime mirrors
                cm = read_mesh(b.read(ref["m_PathID"]))
                P = (np.c_[cm["V"], np.ones(len(cm["V"]))] @ m.T)[:, :3]
                flip = np.linalg.det(m[:3, :3]) < 0
                for tris in cm["subs"]:
                    for t in tris:
                        A, B, C = u2r(P[list(t)])
                        # outward winding in Roblox space: Unity front faces need (a, c, b) after the z flip
                        tri = (A, C, B) if not flip else (A, B, C)
                        collision.append([round(float(x), 3) for v in tri for x in v])
        if bc is not None:
            d = b.read(bc)
            if not d.get("m_IsTrigger"):
                c, s = d["m_Center"], d["m_Size"]
                boxes.append({"name": gname, "matrix": m.round(5).tolist(), "center": [c["x"], c["y"], c["z"]],
                              "size": [s["x"], s["y"], s["z"]]})
        if mf is None or mr is None:
            continue
        mref = b.read(mf)["m_Mesh"]
        if not mref.get("m_PathID") or mref.get("m_FileID") or mref["m_PathID"] not in b.objs:
            continue
        rd = b.read(mr)
        if not rd.get("m_Enabled", 1):
            continue
        mesh = read_mesh(b.read(mref["m_PathID"]))
        P = (np.c_[mesh["V"], np.ones(len(mesh["V"]))] @ M.T)[:, :3]
        if np.linalg.det(m[:3, :3]) < 0:  # mirrored object inside the tile
            subs = [t[:, [0, 2, 1]] for t in mesh["subs"]]
        else:
            subs = mesh["subs"]
        mats = [tile.material(x["m_PathID"]) if x.get("m_PathID") in b.objs else None for x in rd.get("m_Materials", [])]
        base = cap(re.sub(r"[^A-Za-z0-9_]", "_", clean(gname)))
        baked = []  # (tris, material)
        for k, tris in enumerate(subs):
            if not len(tris):
                continue
            mat = mats[min(k, len(mats) - 1)] if mats else None
            sh = mat["shader"] if mat else ""
            col = np.array(mat["colors"].get("_Color", (1, 1, 1, 1))) if mat else np.ones(4)
            if mat is None:
                continue
            if sh in GLOW:
                c = mesh["C"][np.unique(tris)][:, :3].mean(0) * col[:3]
                add_object(unique(f"{base}_Glow"), P, tris, None, None, "glow", color=c)
            elif (sh in BAKED or "_LightMap" in mat["tex"] or "_AOMap" in mat["tex"]) and (mesh["uv1"] is not None or mesh["uv0"] is not None):
                baked.append((tris, mat))
            elif "_MainTex" in mat["tex"] and mesh["uv0"] is not None:
                pid, sc, off = mat["tex"]["_MainTex"]
                img = tile.image(pid)
                if img is None:
                    continue
                fn = os.path.join(a.out, "textures", f"{name}__{unique(base + '_tex')}.png")
                alpha = np.asarray(img)[..., 3].min() < 250 and ("Transparent" in sh or "Alpha" in sh or "Particle" in sh
                                                                 or sh == "" or "Cutout" in sh)
                (img if alpha else img.convert("RGB")).save(fn)
                uv = mesh["uv0"] * np.array(sc) + np.array(off)
                kind = "selfillum" if "Self-Illum" in sh else "tex"
                add_object(unique(f"{base}_Tex"), P, tris, uv, fn, kind, alpha=bool(alpha))
            else:
                c = mesh["C"][np.unique(tris)][:, :3].mean(0) * col[:3]
                add_object(unique(f"{base}_Color"), P, tris, None, None, "color", color=c)
        if baked:
            uvb = mesh["uv1"] if mesh["uv1"] is not None else mesh["uv0"]
            canvas, covered = None, None
            groups = {}
            for tris, mat in baked:
                lmid = mat["tex"].get("_LightMap", (None,))[0]
                if lmid is None and "_AOMap" in mat["tex"]:  # AO-VC: vertex colour x AO (as lightmap alpha, no light)
                    aoid = mat["tex"]["_AOMap"][0]
                    lmid = ("ao", aoid)
                    if lmid not in tile.images:
                        ao = tile.image(aoid)
                        if ao is not None:
                            g8 = ao.convert("L")
                            black = Image.new("L", ao.size, 0)
                            tile.images[lmid] = Image.merge("RGBA", (black, black, black, g8))
                        else:
                            tile.images[lmid] = None
                groups.setdefault(lmid, []).append(tris)
            res = 256
            for lmid in groups:
                lm = tile.image(lmid) if lmid is not None else None
                if lm is not None:
                    res = max(res, min(1024, lm.size[0]))
            for lmid, tl in groups.items():
                lm = tile.image(lmid) if lmid is not None else None
                img, cov = bake_vertex_colour(uvb, np.concatenate(tl), mesh["C"][:, :3], res, lm, a.lm_gain)
                arr = np.asarray(img).copy()
                if canvas is None:
                    canvas, covered = arr, cov
                else:
                    canvas[cov] = arr[cov]
                    covered |= cov
            fn = os.path.join(a.out, "textures", f"{name}__{base}_baked.png")
            Image.fromarray(canvas).save(fn)
            add_object(unique(f"{base}"), P, np.concatenate([t for t, _ in baked]), uvb, fn, "baked")

    # preview render (workbench, textured), looking at the tile from the default brawler side
    info = {"name": name, "source": os.path.basename(a.bundle), "root": a.root, "mirror": a.mirror, "studsPerUnit": K,
            "parts": parts, "collision": collision, "boxes": boxes, "skipped": skipped}
    check(json.dumps([p["name"] for p in parts]), f"{name} part names")
    if parts and not a.no_preview:
        objs = [o for o in scene.objects if o.type == "MESH"]
        lo = np.min([np.array(o.bound_box).min(0) for o in objs], 0)
        hi = np.max([np.array(o.bound_box).max(0) for o in objs], 0)
        ctr, ext = (lo + hi) / 2, float(np.linalg.norm(hi - lo))
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "FLAT"
        scene.display.shading.color_type = "TEXTURE"
        scene.render.resolution_x, scene.render.resolution_y = 900, 600
        cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
        scene.collection.objects.link(cam)
        scene.camera = cam
        cam.data.lens = 28
        cam.data.clip_end = ext * 10
        # Blender -Y = Roblox -Z... look from Roblox +Z/up (Unity -Z, the side the brawler camera sits on)
        cam.location = Vector((ctr[0], ctr[1] - ext * 0.9, ctr[2] + ext * 0.45))
        cam.rotation_euler = (Vector(ctr) - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = os.path.join(a.out, f"{name}_preview.png")
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(cam, do_unlink=True)
    if parts:
        for o in bpy.data.objects:
            o.select_set(o.type == "MESH")
        bpy.ops.export_scene.fbx(filepath=os.path.join(a.out, f"{name}.fbx"), use_selection=True, global_scale=1.0,
                                 apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y",
                                 object_types={"MESH"}, mesh_smooth_type="FACE", add_leaf_bones=False, bake_anim=False,
                                 path_mode="COPY", embed_textures=True)
    json.dump(info, open(os.path.join(a.out, f"{name}.json"), "w"))
    print(f"{name}: parts={len(parts)} tris={sum(p['tris'] for p in parts)} collision_tris={len(collision)} "
          f"boxes={len(boxes)} kinds={sorted({p['kind'] for p in parts})}")


if __name__ == "__main__":
    main()
