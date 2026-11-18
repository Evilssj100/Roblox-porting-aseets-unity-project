"""Make a Roblox-ready copy of an environment .blend built by env_glb_to_blend.py / arena_scene.py.

* keeps the static scene: collections in KEEP (shell + closed floor iris); drops helpers, the hero
  used for scale, animated iris leaves, the under-floor rotor, cameras and lights
* the baked lighting texture's UV set (active render UV) becomes the only UV set + one material per object, so Roblox's
  single-UV MeshParts show the original baked look
* renames everything with RENAME (no original franchise names), splits glass faces to their own object
* scales to studs (k per unit) and moves the floor to height 0 (Z up; FBX import makes it Y up and maps
  Blender +Y to Roblox +Z, so the back wall at +Y lands at +Z: rotate the model 180 degrees in Studio
  if the game expects it at -Z)
* collision mesh exported as its own object "<Map>_Collision" (Studio: invisible, precise collision)
* writes <out>.blend (images packed), <out>.fbx / <out>.glb (upload-ready), <out>.json and a preview render

Usage: python prep_roblox_arena.py <arena.blend> <out_prefix> <MapName> [studs_per_unit] [floor_object]
"""
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

src, out, MAP = sys.argv[1:4]
k = float(sys.argv[4]) if len(sys.argv) > 4 else 2.56
FLOOR_OBJ = sys.argv[5] if len(sys.argv) > 5 else "skrull_boss_arena_FFF_collision_collision"
KEEP = {"Arena", "Aperture_Closed"}
COLLISION = "skrull_boss_arena_closed_collision_collision"
# plates that cover franchise emblems (source units, before scaling): octagon facing -Y with an
# original medallion texture drawn below
COVERS = [{"name": "Medallion", "x0": -5.4, "x1": 5.4, "z0": 13.3, "z1": 25.9, "y": 21.74, "chamfer": 1.7}]
RENAME = [("SkrullShip_Boss_Arena_Aperture_closed", "FloorIris"), ("SkrullShip_Boss_Arena_Aperture", "FloorIris"),
          ("SkrullShip_Boss_Arena", "Shell"), ("skrullShip_Boss_Arena", "Shell"), ("skrull_boss_arena", "arena"),
          ("SkrullShip", "Arena"), ("Skrull", "Arena"), ("skrull", "arena"), ("aperture_door", "IrisDoor"),
          ("slider", "IrisSlider"), ("_stationary", "")]


def clean(name):
    for a, b in RENAME:
        name = name.replace(a, b)
    return name


bpy.ops.wm.open_mainfile(filepath=src)
scene = bpy.context.scene
floor = bpy.data.objects[FLOOR_OBJ]
fz = float(np.mean([(floor.matrix_world @ v.co).z for v in floor.data.vertices]))
keep = [o for o in bpy.data.objects if o.type == "MESH" and any(c.name in KEEP for c in o.users_collection)]
col = bpy.data.objects[COLLISION]
for o in list(bpy.data.objects):
    if o not in keep and o is not col:
        bpy.data.objects.remove(o, do_unlink=True)
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
objs = keep + [col]
for o in objs:
    if o.name not in scene.collection.objects:
        scene.collection.objects.link(o)
def medallion_png(path, size=512):
    """original emblem: a five-pointed star in a double ring on the arena's panel teal"""
    from PIL import Image, ImageDraw, ImageFilter
    import math
    im = Image.new("RGB", (size, size), (34, 112, 142))
    d = ImageDraw.Draw(im)
    c, R = size / 2, size * 0.40
    d.ellipse([c - R, c - R, c + R, c + R], outline=(168, 226, 232), width=int(size * 0.035))
    r2 = R * 0.84
    d.ellipse([c - r2, c - r2, c + r2, c + r2], fill=(46, 140, 172), outline=(120, 200, 214), width=int(size * 0.012))
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r2 * (0.82 if i % 2 == 0 else 0.36)
        pts.append((c + rr * math.cos(a), c + rr * math.sin(a)))
    d.polygon(pts, fill=(176, 232, 236), outline=(222, 250, 252))
    im = im.filter(ImageFilter.SMOOTH)
    im.save(path)


def cover_plate(cv, png):
    """octagonal plate in the XZ plane (source units), normal -Y, planar UVs"""
    import bmesh
    x0, x1, z0, z1, y, ch = cv["x0"], cv["x1"], cv["z0"], cv["z1"], cv["y"], cv["chamfer"]
    outline = [(x0 + ch, z0), (x1 - ch, z0), (x1, z0 + ch), (x1, z1 - ch), (x1 - ch, z1), (x0 + ch, z1), (x0, z1 - ch), (x0, z0 + ch)]
    me = bpy.data.meshes.new(cv["name"])
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z)) for x, z in outline]
    f = bm.faces.new(vs)
    f.normal_update()
    if f.normal.y > 0:
        f.normal_flip()
    uv = bm.loops.layers.uv.new("UVMap")
    w, h = x1 - x0, z1 - z0
    side = max(w, h)
    for loop in f.loops:
        co = loop.vert.co
        loop[uv].uv = (0.5 + (co.x - (x0 + x1) / 2) / side, 0.5 + (co.z - (z0 + z1) / 2) / side)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(cv["name"], me)
    scene.collection.objects.link(ob)
    img = bpy.data.images.load(png)
    mat = bpy.data.materials.new(cv["name"] + "_mat")
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    img.name = cv["name"] + "_baked"
    mat.node_tree.links.new(tex.outputs["Color"], next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"])
    me.materials.append(mat)
    return ob


for cv in COVERS:
    png = out + f"_{cv['name']}.png"
    medallion_png(png)
    objs_cover = cover_plate(cv, png)
    keep.append(objs_cover)
    objs.append(objs_cover)

# bake world transforms into the meshes, scale to studs, floor at 0
S = Matrix.Diagonal((k, k, k, 1.0)) @ Matrix.Translation((0, 0, -fz))
for o in objs:
    mw = o.matrix_world.copy()
    o.parent = None
    o.data = o.data.copy()
    o.data.transform(S @ mw)
    if (S @ mw).determinant() < 0:  # mirrored objects (scale -1): keep faces pointing out
        o.data.flip_normals()
    o.matrix_world = Matrix.Identity(4)

# glass faces -> own object (Roblox: transparency)
shell = next(o for o in keep if o.name == "SkrullShip_Boss_Arena")
gi = next((i for i, m in enumerate(shell.data.materials) if m and any(n.type == "TEX_IMAGE" and n.image and "glass" in n.image.name
                                                                       for n in m.node_tree.nodes)), None)
if gi is not None:
    bpy.ops.object.select_all(action="DESELECT")
    shell.select_set(True)
    bpy.context.view_layer.objects.active = shell
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    shell.active_material_index = gi
    bpy.ops.object.material_slot_select()
    bpy.ops.mesh.separate(type="SELECTED")
    bpy.ops.object.mode_set(mode="OBJECT")
    glass = next(o for o in bpy.context.selected_objects if o is not shell)
    glass.name = "SkrullShip_Boss_Arena_Glass"
    objs.append(glass)

info = {"map": MAP, "studsPerUnit": k, "floorUnityHeight": fz, "objects": []}
for o in objs:
    me = o.data
    is_col = o is col
    base = clean(o.name).replace("_collision_collision", "_Collision")
    o.name = me.name = f"{MAP}_Collision" if is_col else f"{MAP}_{base}"
    if not is_col:
        # baked image = the texture found on any material of the object
        img = None
        for m in me.materials:
            if m and m.node_tree:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image and "baked" in n.image.name:
                        img = n.image
        # the baked image is sampled with the active render UV set: keep only that one
        render_uv = next((u.name for u in me.uv_layers if u.active_render), me.uv_layers[0].name)
        for u in [u.name for u in me.uv_layers if u.name != render_uv]:
            me.uv_layers.remove(me.uv_layers[u])
        me.uv_layers[0].name = "UVMap"
        mat = bpy.data.materials.new(o.name)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        if img:
            img.name = o.name + "_baked"
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = img
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        me.materials.clear()
        me.materials.append(mat)
    else:
        me.materials.clear()
        while me.uv_layers:
            me.uv_layers.remove(me.uv_layers[0])
    P = np.array([v.co[:] for v in me.vertices])
    info["objects"].append({"name": o.name, "collision": is_col, "verts": len(me.vertices), "tris": sum(len(p.vertices) - 2 for p in me.polygons),
                            "min": P.min(0).round(3).tolist(), "max": P.max(0).round(3).tolist()})
# importer-safe meshes: triangulated, every mesh with a UV set and a material
import bmesh  # noqa: E402
for o in objs:
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(o.data)
    bm.free()
    if not o.data.uv_layers:
        o.data.uv_layers.new(name="UVMap")
    if not o.data.materials:
        mat = bpy.data.materials.new(o.name + "_mat")
        o.data.materials.append(mat)
for im in list(bpy.data.images):
    if im.users == 0:
        bpy.data.images.remove(im)
    else:
        im.pack()
for m in list(bpy.data.materials):
    if m.users == 0:
        bpy.data.materials.remove(m)
for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)

# preview (from the arena front, looking at the back wall)
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "TEXTURE"
scene.render.resolution_x, scene.render.resolution_y = 1000, 600
col.hide_render = True
cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = Vector((0, -55, 40))
cam.data.lens = 22
cam.rotation_euler = (Vector((0, 20, 8)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.render.filepath = out + "_preview.png"
bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(cam, do_unlink=True)
col.hide_render = False
bpy.ops.wm.save_as_mainfile(filepath=out + ".blend", compress=True)
# upload-ready exports (studs already applied): FBX like the Roblox Uploader add-on, plus GLB
for o in bpy.data.objects:
    o.select_set(o.type == "MESH")
bpy.ops.export_scene.fbx(filepath=out + ".fbx", use_selection=True, global_scale=1.0, apply_scale_options="FBX_SCALE_UNITS",
                         axis_forward="-Z", axis_up="Y", object_types={"MESH"}, mesh_smooth_type="FACE", add_leaf_bones=False,
                         bake_anim=False, path_mode="COPY", embed_textures=True)
bpy.ops.export_scene.gltf(filepath=out + ".glb", use_selection=True, export_format="GLB", export_yup=True, export_apply=True,
                          export_animations=False)
json.dump(info, open(out + ".json", "w"), indent=1)
print(json.dumps({o["name"]: o["tris"] for o in info["objects"]}), "floor z (units)", round(fz, 3))
