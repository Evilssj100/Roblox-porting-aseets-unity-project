"""Merge many port_tile.py models (one FBX + JSON each) into ONE upload: a single FBX whose parts are renamed
"<Model>__<n>" (so a setup script can split them back into per-model templates) and a JSON with every model's
parts, collision triangles and boxes. Identical textures are embedded once.

Usage: python merge_props.py <out_prefix> <model_dir> <Model1> [<Model2> ...]
"""
import hashlib
import json
import os
import sys

import bpy  # noqa: F401

out_prefix, src = sys.argv[1:3]
models = sys.argv[3:]
bpy.ops.wm.read_factory_settings(use_empty=True)
info = {}
by_hash = {}
for m in models:
    js = json.load(open(os.path.join(src, f"{m}.json")))
    if not js["parts"]:
        continue
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.join(src, f"{m}.fbx"), axis_forward="-Z", axis_up="Y")
    new = [o for o in bpy.data.objects if o not in before]
    parts = {}
    for i, o in enumerate(sorted(new, key=lambda o: o.name)):
        if o.type != "MESH":
            continue
        p = next((p for p in js["parts"] if p["name"] == o.name.split(".")[0]), None)
        if p is None:
            continue
        name = f"{m}__{i + 1}"
        o.name = o.data.name = name
        for slot in o.material_slots:
            mat = slot.material
            if not (mat and mat.node_tree):
                continue
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    im = n.image
                    try:
                        data = im.packed_file.data if im.packed_file else open(bpy.path.abspath(im.filepath), "rb").read()
                    except OSError:
                        data = im.name.encode()
                    h = hashlib.sha1(data).hexdigest()
                    if h in by_hash and by_hash[h] is not im:
                        n.image = by_hash[h]
                    else:
                        by_hash[h] = im
        parts[name] = {k: v for k, v in p.items() if k not in ("name", "tris", "size")}
    info[m] = {"parts": parts, "collision": js["collision"], "boxes": js.get("boxes", [])}
for im in list(bpy.data.images):
    if im.users == 0:
        bpy.data.images.remove(im)
    elif not im.packed_file:
        im.pack()
for o in bpy.data.objects:
    o.select_set(o.type == "MESH")
bpy.ops.export_scene.fbx(filepath=out_prefix + ".fbx", use_selection=True, global_scale=1.0, apply_scale_options="FBX_SCALE_UNITS",
                         axis_forward="-Z", axis_up="Y", object_types={"MESH"}, mesh_smooth_type="FACE", add_leaf_bones=False,
                         bake_anim=False, path_mode="COPY", embed_textures=True)
json.dump(info, open(out_prefix + ".json", "w"))
print(f"{os.path.basename(out_prefix)}: {len(info)} models, {sum(len(v['parts']) for v in info.values())} parts, "
      f"{len([i for i in bpy.data.images if i.users])} images, {os.path.getsize(out_prefix + '.fbx') / 1e6:.1f} MB")
