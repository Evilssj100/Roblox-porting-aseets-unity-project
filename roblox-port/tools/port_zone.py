"""Port an original social zone's geometry (archive SocialSpace/<zone>.asset) to Roblox-ready FBX files,
built straight in (cloud) Blender:

* everything in Unity world space (the zone bundles are instantiated as they are), Roblox axes, studs
* textured materials (AO-Tex, Lightmap-Tex, Self-Illum-Tex, Diffuse...) keep their own tiling textures on
  uv0 (Roblox lights them), merged into one part per texture; vertex-colour materials (LightMap-VC, AO-VC,
  VertexColor) are baked (colour x AO/lightmap) into 1024 atlas pages and merged per page; Self-Illum
  becomes Neon parts (one per colour); low LODs are left out
* collision: concave and convex MeshColliders in grid chunks (invisible MeshParts, set to precise convex
  decomposition in Studio), BoxColliders as boxes in the JSON
* parts are split to stay under the triangle and 2048-stud limits; textures are shared, never copied
* writes <out>/<Zone>_<n>.fbx (several files, each under the upload budget), <Zone>.json, <Zone>_preview.png

Usage: python port_zone.py <bundle.asset> <out_dir> --name Zone --roots Root1,Root2 [--skip REGEX] [--density 6]
"""
import argparse
import io
import json
import math
import os
import re
import sys

import bpy  # noqa: F401
import numpy as np
from mathutils import Vector
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from port_tile import K, Tile, read_mesh, trs, u2b, u2r  # noqa: E402
from spso_names import check, clean  # noqa: E402
from unity_yaml_scene_to_glb import bake_vertex_colour  # noqa: E402

VC_SHADERS = {"LightMap-VC", "AO-VC", "VertexColor", "LightMap-VC-Illum", "Lightmap/VertexColor", "VertexLit-VC"}
GLOW_SHADERS = {"Self-Illum"}
PAGE = 1024
LOW_LOD = r"(?i)(lod_?(hz_)?low|_lod[12]\b|_low$)"


def tri_area(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


class Atlas:
    """power-of-two blocks in PAGE x PAGE pages (buddy allocation)"""

    def __init__(self):
        self.pages = []  # list of PIL images
        self.free = []  # (page, x, y, size)

    def alloc(self, size):
        best = None
        for i, (p, x, y, s) in enumerate(self.free):
            if s >= size and (best is None or s < self.free[best][3]):
                best = i
        if best is None:
            self.pages.append(Image.new("RGB", (PAGE, PAGE), (128, 128, 128)))
            self.free.append((len(self.pages) - 1, 0, 0, PAGE))
            return self.alloc(size)
        p, x, y, s = self.free.pop(best)
        while s > size:
            s //= 2
            self.free += [(p, x + s, y, s), (p, x, y + s, s), (p, x + s, y + s, s)]
        return p, x, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("out")
    ap.add_argument("--name", required=True)
    ap.add_argument("--roots", required=True, help="comma separated root GameObjects (geometry, boundary...)")
    ap.add_argument("--skip", default=None)
    ap.add_argument("--no-render", default=None, help="regex: these objects keep their colliders but are not drawn")
    ap.add_argument("--density", type=float, default=6.0, help="baked texels per stud")
    ap.add_argument("--tri-limit", type=int, default=15000)
    ap.add_argument("--cell", type=float, default=64.0, help="collision chunk size (studs)")
    ap.add_argument("--fbx-budget", type=float, default=28.0, help="MB of textures per FBX")
    ap.add_argument("--lm-gain", type=float, default=1.0)
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--remove", action="append", default=[],
                    help="object:x0,y0,z0,x1,y1,z1[:gold] - drop that object's triangles inside the box (Unity world), "
                         "optionally only gold-coloured ones (franchise lettering)")
    a = ap.parse_args()
    removes = []
    for r in a.remove:
        parts_ = r.split(":")
        removes.append((parts_[0], np.array([float(x) for x in parts_[1].split(",")]).reshape(2, 3),
                        parts_[2] if len(parts_) > 2 else None))
    Z = a.name
    os.makedirs(os.path.join(a.out, "textures"), exist_ok=True)
    skip = re.compile(a.skip) if a.skip else None
    lowlod = re.compile(LOW_LOD)

    tile = None
    items = {"tex": {}, "glow": {}, "color": {}}  # key -> list of (P, T, uv)
    baked = []  # (P, T, uv, colours, lm image, area)
    col_tris, boxes = [], []
    tex_info = {}
    stats = {"renderers": 0, "skipped": [], "tris": 0}
    for rname in a.roots.split(","):
        tile = Tile(a.bundle, rname) if tile is None else tile
        b = tile.b
        roots = sorted([g for g in b.tr_of_go if b.name(g) == rname], key=lambda g: len(b.path(g)))
        if not roots:
            print("missing root", rname)
            continue
        stack = [(roots[0], trs(b.read(b.tr_of_go[roots[0]])))]
        while stack:
            g, M = stack.pop()
            gname = b.name(g)
            if (skip and skip.search(gname)) or lowlod.search(gname):
                stats["skipped"].append(gname)
                continue
            for k in b.children.get(g, []):
                stack.append((k, M @ trs(b.read(b.tr_of_go[k]))))
            flip = np.linalg.det(M[:3, :3]) < 0
            for cid in b.components(g):
                t = b.type(cid)
                if t == "MeshCollider":
                    d = b.read(cid)
                    ref = d["m_Mesh"]
                    if d.get("m_IsTrigger") or ref.get("m_PathID") not in b.objs:
                        continue
                    cm = read_mesh(b.read(ref["m_PathID"]))
                    P = (np.c_[cm["V"], np.ones(len(cm["V"]))] @ M.T)[:, :3]
                    R = u2r(P)
                    for tris in cm["subs"]:
                        for tr in tris:
                            A, B, C = R[list(tr)]
                            col_tris.append((A, C, B) if not flip else (A, B, C))
                elif t == "BoxCollider":
                    d = b.read(cid)
                    if d.get("m_IsTrigger") or not d.get("m_Enabled", 1):
                        continue
                    c, s = d["m_Center"], d["m_Size"]
                    sc = np.linalg.norm(M[:3, :3], axis=0)
                    Rm = M[:3, :3] / np.where(sc == 0, 1, sc)
                    ctr = M[:3, :3] @ np.array([c["x"], c["y"], c["z"]]) + M[:3, 3]
                    Pm = np.diag([1.0, 1, -1])
                    boxes.append({"name": clean(gname), "cf": [round(float(v), 4) for v in Pm @ ctr * K] +
                                  [round(float(v), 6) for v in (Pm @ Rm @ Pm).reshape(-1)],
                                  "size": [round(float(v), 4) for v in np.array([s["x"], s["y"], s["z"]]) * sc * K]})
            mf, mr = b.comp(g, "MeshFilter"), b.comp(g, "MeshRenderer")
            if mf is None or mr is None or (a.no_render and re.search(a.no_render, gname)):
                continue
            rd = b.read(mr)
            mref = b.read(mf)["m_Mesh"]
            if not rd.get("m_Enabled", 1) or mref.get("m_PathID") not in b.objs or mref.get("m_FileID"):
                continue
            try:
                mesh = read_mesh(b.read(mref["m_PathID"]))
            except Exception as e:  # noqa: BLE001
                print("mesh failed", gname, e)
                continue
            stats["renderers"] += 1
            P = (np.c_[mesh["V"], np.ones(len(mesh["V"]))] @ M.T)[:, :3]
            subs = [s[:, [0, 2, 1]] for s in mesh["subs"]] if flip else mesh["subs"]
            for oname, box, rule in removes:
                if oname != gname:
                    continue
                kept = []
                for T in subs:
                    cen = P[T].mean(1)
                    inside = np.all((cen >= box[0]) & (cen <= box[1]), axis=1)
                    if rule == "gold":
                        C = mesh["C"][T].mean(1)[:, :3]
                        inside &= (C[:, 0] > 0.55) & (C[:, 1] > 0.45) & (C[:, 2] < 0.45)
                    stats.setdefault("removed", {})[gname] = stats.get("removed", {}).get(gname, 0) + int(inside.sum())
                    kept.append(T[~inside])
                subs = kept
            mats = [tile.material(x["m_PathID"]) if x.get("m_PathID") in b.objs else None for x in rd.get("m_Materials", [])]
            bake_parts = []
            for k, T in enumerate(subs):
                if not len(T) or not mats:
                    continue
                mat = mats[min(k, len(mats) - 1)]
                if mat is None:
                    continue
                stats["tris"] += len(T)
                sh = mat["shader"]
                col = np.array(mat["colors"].get("_Color", (1, 1, 1, 1)))
                if sh in GLOW_SHADERS:
                    c = mesh["C"][np.unique(T)][:, :3].mean(0) * col[:3]
                    key = tuple(np.round(np.clip(c, 0, 1) * 16) / 16)
                    items["glow"].setdefault(key, []).append((P, T, None))
                elif "_MainTex" in mat["tex"] and mesh["uv0"] is not None:
                    pid, sc, off = mat["tex"]["_MainTex"]
                    if pid not in tex_info:
                        img = tile.image(pid)
                        if img is None:
                            continue
                        arr = np.asarray(img)
                        alpha = bool(arr[..., 3].min() < 250) and ("Alpha" in sh or "Transparent" in sh or "Cutout" in sh
                                                                  or sh == "" or "Particle" in sh)
                        tname = re.sub(r"[^A-Za-z0-9_]", "_", clean(b.read(pid)["m_Name"]))
                        fn = os.path.join(a.out, "textures", f"{Z}__{tname}_{pid % 10000}.png")
                        im = img if alpha else img.convert("RGB")
                        if max(im.size) > 1024:
                            im = im.resize((min(1024, im.size[0]), min(1024, im.size[1])), Image.LANCZOS)
                        im.save(fn)
                        tex_info[pid] = {"file": fn, "alpha": alpha, "bytes": os.path.getsize(fn),
                                         "selfillum": "Self-Illum" in sh or "Illum" in sh}
                    uv = mesh["uv0"] * np.array(sc) + np.array(off)
                    items["tex"].setdefault(pid, []).append((P, T, uv))
                elif (sh in VC_SHADERS or "_LightMap" in mat["tex"] or "_AOMap" in mat["tex"]) and \
                        (mesh["uv1"] is not None or mesh["uv0"] is not None):
                    bake_parts.append((T, mat))
                else:
                    c = mesh["C"][np.unique(T)][:, :3].mean(0) * col[:3]
                    key = tuple(np.round(np.clip(c, 0, 1) * 16) / 16)
                    items["color"].setdefault(key, []).append((P, T, None))
            if bake_parts:
                uvb = mesh["uv1"] if mesh["uv1"] is not None else mesh["uv0"]
                T = np.concatenate([t for t, _ in bake_parts])
                mat = bake_parts[0][1]
                lm = None
                if "_LightMap" in mat["tex"]:
                    lm = tile.image(mat["tex"]["_LightMap"][0])
                elif "_AOMap" in mat["tex"]:
                    ao = tile.image(mat["tex"]["_AOMap"][0])
                    if ao is not None:
                        g8 = ao.convert("L")
                        black = Image.new("L", ao.size, 0)
                        lm = Image.merge("RGBA", (black, black, black, g8))
                area = float(tri_area(u2r(P), T).sum())
                baked.append((P, T, np.clip(uvb, 0, 1), mesh["C"][:, :3], lm, area))

    # ---- bake the vertex-colour objects into atlas pages
    atlas = Atlas()
    baked_items = {}  # page -> list of (P, T, uv)
    order = sorted(range(len(baked)), key=lambda i: -baked[i][5])
    for i in order:
        P, T, uv, C, lm, area = baked[i]
        res = int(2 ** round(math.log2(max(16.0, math.sqrt(max(area, 1.0)) * a.density))))
        res = max(16, min(512, res))
        img, _ = bake_vertex_colour(uv, T, C, res, lm, a.lm_gain)
        p, x, y = atlas.alloc(res)
        atlas.pages[p].paste(img, (x, y))
        half = 0.5 / res
        u = half + uv[:, 0] * (1 - 2 * half)
        v = half + uv[:, 1] * (1 - 2 * half)
        auv = np.stack([(x + u * res) / PAGE, 1 - (y + (1 - v) * res) / PAGE], 1)
        baked_items.setdefault(p, []).append((P, T, auv))
    page_files = []
    for p, im in enumerate(atlas.pages):
        fn = os.path.join(a.out, "textures", f"{Z}__atlas{p}.png")
        im.save(fn)
        page_files.append(fn)

    # ---- build merged Blender objects
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    parts, images = [], {}
    count = {}

    def bimage(fn):
        if fn not in images:
            im = bpy.data.images.load(fn)
            im.name = os.path.splitext(os.path.basename(fn))[0]
            im.pack()
            images[fn] = im
        return images[fn]

    def emit(kind, group, img_fn=None, color=None, alpha=False, selfillum=False):
        """merge a group of (P, T, uv) into objects, split by triangle count and extent"""
        Ps, Ts, UVs, off = [], [], [], 0
        for P, T, uv in group:
            used = np.unique(T)
            remap = -np.ones(len(P), np.int64)
            remap[used] = np.arange(len(used)) + off
            Ps.append(P[used])
            UVs.append(uv[used] if uv is not None else np.zeros((len(used), 2)))
            Ts.append(remap[T])
            off += len(used)
        P, T, UV = np.concatenate(Ps), np.concatenate(Ts), np.concatenate(UVs)
        split(kind, P, T, UV, img_fn, color, alpha, selfillum)

    def split(kind, P, T, UV, img_fn, color, alpha, selfillum):
        ext = np.ptp(u2r(P[np.unique(T)]), axis=0)
        if (len(T) > a.tri_limit or ext.max() > 1900) and len(T) > 1:
            ax = int(np.argmax(ext))
            cen = P[T].mean(1)[:, [0, 1, 2][ax]] if ax != 2 else -P[T].mean(1)[:, 2]
            cut = np.median(cen)
            lo, hi = T[cen <= cut], T[cen > cut]
            if len(lo) and len(hi):
                split(kind, P, lo, UV, img_fn, color, alpha, selfillum)
                split(kind, P, hi, UV, img_fn, color, alpha, selfillum)
                return
        used = np.unique(T)
        remap = -np.ones(len(P), np.int64)
        remap[used] = np.arange(len(used))
        Pu, Tu, UVu = P[used], remap[T][:, [0, 2, 1]], UV[used]
        count[kind] = count.get(kind, 0) + 1
        name = f"{Z}_{kind.capitalize()}{count[kind]}"
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in u2b(Pu)], [], [tuple(t) for t in Tu])
        me.update()
        uvl = me.uv_layers.new(name="UVMap")
        loops = np.array([l.vertex_index for l in me.loops])
        uvl.data.foreach_set("uv", UVu[loops].astype(np.float32).ravel())
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        if img_fn:
            tn = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tn.image = bimage(img_fn)
            mat.node_tree.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
        elif color is not None:
            bsdf.inputs["Base Color"].default_value = (*color[:3], 1.0)
        me.materials.append(mat)
        ob = bpy.data.objects.new(name, me)
        scene.collection.objects.link(ob)
        R = u2r(Pu)
        lo, hi = R.min(0), R.max(0)
        parts.append({"name": name, "kind": kind, "center": ((lo + hi) / 2).round(4).tolist(), "size": (hi - lo).round(4).tolist(),
                      "tris": int(len(Tu)), "texture": os.path.basename(img_fn) if img_fn else None,
                      **({"color": [round(float(c), 4) for c in color[:3]]} if color is not None else {}),
                      **({"alpha": True} if alpha else {}), **({"selfillum": True} if selfillum else {})})

    for p, group in baked_items.items():
        emit("baked", group, page_files[p])
    for pid, group in items["tex"].items():
        ti = tex_info[pid]
        emit("tex", group, ti["file"], alpha=ti["alpha"], selfillum=ti["selfillum"])
    for key, group in items["glow"].items():
        emit("glow", group, color=key)
    for key, group in items["color"].items():
        emit("color", group, color=key)

    # collision chunks (grid cells by triangle centroid)
    cells = {}
    for tri in col_tris:
        c = (tri[0] + tri[1] + tri[2]) / 3
        cells.setdefault((int(c[0] // a.cell), int(c[2] // a.cell)), []).append(tri)
    collision = []
    for key, tl in sorted(cells.items()):
        V = np.array([v for t in tl for v in t])
        T = np.arange(len(V)).reshape(-1, 3)
        Pu = np.stack([V[:, 0], V[:, 1], -V[:, 2]], 1) / K  # back to Unity space for u2b
        count["col"] = count.get("col", 0) + 1
        name = f"{Z}_Col{count['col']}"
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in u2b(Pu)], [], [tuple(t) for t in T[:, [0, 2, 1]]])
        me.update()
        me.uv_layers.new(name="UVMap")
        mat = bpy.data.materials.new(name)
        me.materials.append(mat)
        ob = bpy.data.objects.new(name, me)
        scene.collection.objects.link(ob)
        lo, hi = V.min(0), V.max(0)
        collision.append({"name": name, "center": ((lo + hi) / 2).round(4).tolist(), "size": (hi - lo).round(4).tolist(),
                          "tris": len(T)})
        ob["spso_collision"] = True
    # merge doubles in collision chunks keeps decomposition clean
    for o in scene.objects:
        if o.get("spso_collision"):
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.01)
            bm.to_mesh(o.data)
            bm.free()

    info = {"name": Z, "source": os.path.basename(a.bundle), "roots": a.roots.split(","), "studsPerUnit": K,
            "parts": parts, "collision": collision, "boxes": boxes,
            "stats": {**stats, "skipped": stats["skipped"][:50], "pages": len(atlas.pages), "textures": len(tex_info)}}
    check(json.dumps([p["name"] for p in parts] + [c["name"] for c in collision]), f"{Z} names")

    # preview
    objs = [o for o in scene.objects if o.type == "MESH" and not o.get("spso_collision")]
    if objs and not a.no_preview:
        for o in scene.objects:
            if o.get("spso_collision"):
                o.hide_render = True
        lo = np.min([np.array(o.bound_box).min(0) for o in objs], 0)
        hi = np.max([np.array(o.bound_box).max(0) for o in objs], 0)
        ctr, ext = (lo + hi) / 2, float(np.linalg.norm(hi - lo))
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "TEXTURE"
        scene.render.resolution_x, scene.render.resolution_y = 1400, 900
        cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
        scene.collection.objects.link(cam)
        scene.camera = cam
        cam.data.lens = 24
        cam.data.clip_end = ext * 10
        cam.location = Vector((ctr[0], ctr[1] - ext * 0.45, ctr[2] + ext * 0.35))
        cam.rotation_euler = (Vector(ctr) - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = os.path.join(a.out, f"{Z}_preview.png")
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(cam, do_unlink=True)
        for o in scene.objects:
            o.hide_render = False

    # FBX files under the texture budget: atlases, colours and collision in the first file, textured groups spread
    groups, cur, cur_bytes = [], [], 0.0
    first = [o for o in scene.objects if o.type == "MESH" and (o.get("spso_collision") or not any(
        p["name"] == o.name and p["kind"] == "tex" for p in parts))]
    tex_objs = [o for o in scene.objects if o.type == "MESH" and o not in first]
    first_bytes = sum(os.path.getsize(f) for f in page_files) / 1e6
    groups.append(first)
    cur, cur_bytes, seen = [], 0.0, set()
    for o in sorted(tex_objs, key=lambda o: o.name):
        tex = next(p["texture"] for p in parts if p["name"] == o.name)
        size = 0.0 if tex in seen else os.path.getsize(os.path.join(a.out, "textures", tex)) / 1e6
        if cur and cur_bytes + size > a.fbx_budget:
            groups.append(cur)
            cur, cur_bytes, seen = [], 0.0, set()
            size = os.path.getsize(os.path.join(a.out, "textures", tex)) / 1e6
        cur.append(o)
        cur_bytes += size
        seen.add(tex)
    if cur:
        groups.append(cur)
    files = []
    for i, g in enumerate(groups):
        if not g:
            continue
        for o in scene.objects:
            o.select_set(o in g)
        fn = os.path.join(a.out, f"{Z}_{i + 1}.fbx")
        bpy.ops.export_scene.fbx(filepath=fn, use_selection=True, global_scale=1.0, apply_scale_options="FBX_SCALE_UNITS",
                                 axis_forward="-Z", axis_up="Y", object_types={"MESH"}, mesh_smooth_type="FACE",
                                 add_leaf_bones=False, bake_anim=False, path_mode="COPY", embed_textures=True)
        files.append({"file": os.path.basename(fn), "objects": [o.name for o in g], "mb": round(os.path.getsize(fn) / 1e6, 2)})
    info["files"] = files
    json.dump(info, open(os.path.join(a.out, f"{Z}.json"), "w"))
    kinds = {}
    for p in parts:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print(f"{Z}: renderers {stats['renderers']} tris {stats['tris']} -> parts {len(parts)} {kinds}, atlas pages "
          f"{len(atlas.pages)}, textures {len(tex_info)}, collision chunks {len(collision)} ({len(col_tris)} tris), "
          f"boxes {len(boxes)}, files {[(f['file'], f['mb']) for f in files]}")


if __name__ == "__main__":
    main()
