"""The social-zone pickups as one upload (Hub_Pickups.fbx + .json), parts named "<Model>__<n>" like merge_props.py:

* Fractal: the original fractal shard mesh (port_tile.py export of the activity bundle's fractal_shard_01); the
  game draws it as a glowing crystal
* HeroToken: an original coin (bevelled disc with a raised five-point star on both faces); the original token face
  carried a franchise logo, so it is not used
* Star: an original puffy five-point star (the poke-a-prop reward)
All in studs, standing upright (they spin around the vertical axis in game).

Usage: python build_hub_pickups.py <pickups_dir> <out_prefix>
"""
import json
import math
import os
import sys

import bpy  # noqa: I001 (bpy first: it puts bmesh on the path)
import bmesh

src, out_prefix = sys.argv[1:3]
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
info = {}


def material(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    return m


def star_outline(r_out, r_in, n=5, phase=math.pi / 2):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = phase + i * math.pi / n
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def prism(bm, outline, z0, z1):
    """a closed prism of a star-shaped outline between z0 and z1 (fan from the centre: stays valid for concave stars)"""
    c0, c1 = bm.verts.new((0, 0, z0)), bm.verts.new((0, 0, z1))
    lo = [bm.verts.new((x, y, z0)) for x, y in outline]
    hi = [bm.verts.new((x, y, z1)) for x, y in outline]
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((c0, lo[j], lo[i]))
        bm.faces.new((c1, hi[i], hi[j]))
        bm.faces.new((lo[i], lo[j], hi[j], hi[i]))


def finish(name, bm, mat, upright=True):
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers.new(name="UVMap")
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    if upright:  # disc/star lying in XY -> standing, facing Blender -Y (Roblox +Z)
        ob.rotation_euler = (math.pi / 2, 0, 0)
        bpy.context.view_layer.update()
        ob.data.transform(ob.matrix_world)
        ob.matrix_world.identity()
    return ob


def part_info(ob, kind, color):
    xs = [v.co for v in ob.data.vertices]
    lo = [min(v[i] for v in xs) for i in range(3)]
    hi = [max(v[i] for v in xs) for i in range(3)]
    # Blender (X, Y, Z) -> Roblox (-X, Z, Y) on FBX import
    ctr = [-(lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2, (lo[1] + hi[1]) / 2]
    return {"kind": kind, "center": [round(c, 4) for c in ctr], "color": color}


# Fractal: the original shard mesh -----------------------------------------------------------------------------------
before = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=os.path.join(src, "Hub_Fractal.fbx"), axis_forward="-Z", axis_up="Y")
shard = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
for i, o in enumerate(shard):
    o.name = o.data.name = f"Fractal__{i + 1}"
    o.data.materials.clear()
    o.data.materials.append(material("Fractal", (0.69, 0.41, 1.0)))
    # bake the transform, stand the shard on its long axis, 2.4 studs tall, centred
    o.data.transform(o.matrix_world)
    o.matrix_world.identity()
    xs = [v.co.copy() for v in o.data.vertices]
    dims = [max(v[k] for v in xs) - min(v[k] for v in xs) for k in range(3)]
    long_axis = dims.index(max(dims))
    from mathutils import Matrix
    if long_axis == 1:
        o.data.transform(Matrix.Rotation(math.pi / 2, 4, "X"))
    elif long_axis == 0:
        o.data.transform(Matrix.Rotation(math.pi / 2, 4, "Y"))
    xs = [v.co.copy() for v in o.data.vertices]
    lo = [min(v[k] for v in xs) for k in range(3)]
    hi = [max(v[k] for v in xs) for k in range(3)]
    s = 2.4 / max(hi[2] - lo[2], 1e-6)
    o.data.transform(Matrix.Scale(s, 4) @ Matrix.Translation([-(lo[k] + hi[k]) / 2 for k in range(3)]))
info["Fractal"] = {"parts": {o.name: part_info(o, "glow", [0.69, 0.41, 1.0]) for o in shard}}

# HeroToken: an original coin ------------------------------------------------------------------------------------------
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=40, radius1=0.95, radius2=0.95, depth=0.22)
bmesh.ops.bevel(bm, geom=[e for e in bm.edges if abs(e.verts[0].co.z) > 0.1 and abs(e.verts[1].co.z) > 0.1],
                offset=0.06, segments=2, affect="EDGES")
for z in (0.11, -0.11):
    prism(bm, star_outline(0.55, 0.23), z, z + (0.07 if z > 0 else -0.07))
coin = finish("HeroToken__1", bm, material("HeroToken", (1.0, 0.8, 0.24)))
info["HeroToken"] = {"parts": {coin.name: part_info(coin, "color", [1.0, 0.8, 0.24])}}

# Star: an original puffy star -------------------------------------------------------------------------------------------
bm = bmesh.new()
outline = star_outline(0.9, 0.42)
c_front, c_back = bm.verts.new((0, 0, 0.32)), bm.verts.new((0, 0, -0.32))
ring = [bm.verts.new((x, y, 0)) for x, y in outline]
n = len(ring)
for i in range(n):
    j = (i + 1) % n
    bm.faces.new((c_front, ring[i], ring[j]))
    bm.faces.new((c_back, ring[j], ring[i]))
star = finish("Star__1", bm, material("Star", (0.6, 0.9, 1.0)))
info["Star"] = {"parts": {star.name: part_info(star, "glow", [0.6, 0.9, 1.0])}}

for o in bpy.data.objects:
    o.select_set(o.type == "MESH")
bpy.ops.export_scene.fbx(filepath=out_prefix + ".fbx", use_selection=True, global_scale=1.0, apply_scale_options="FBX_SCALE_UNITS",
                         axis_forward="-Z", axis_up="Y", object_types={"MESH"}, mesh_smooth_type="FACE", add_leaf_bones=False,
                         bake_anim=False, path_mode="COPY", embed_textures=True)
json.dump(info, open(out_prefix + ".json", "w"), indent=1)
print({k: list(v["parts"]) for k, v in info.items()}, os.path.getsize(out_prefix + ".fbx"))
