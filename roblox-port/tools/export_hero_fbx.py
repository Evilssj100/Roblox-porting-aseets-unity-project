"""Export a Roblox-ready hero .blend (from prep_roblox_hero.py) to FBX exactly the way the Roblox Uploader
add-on does (studs per unit as global_scale, -Z forward, Y up, no leaf bones, no animation, textures
embedded). Run it in the cloud: the upload from the user's Blender is then a plain file POST, with no
export in their Blender.

Usage: python export_hero_fbx.py <hero.blend> <out.fbx> [studs_per_unit]
"""
import os
import sys

import bpy

src, out = sys.argv[1:3]
k = float(sys.argv[3]) if len(sys.argv) > 3 else 2.56
bpy.ops.wm.open_mainfile(filepath=src)
for o in bpy.data.objects:
    if o.animation_data:
        o.animation_data.action = None
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
for im in bpy.data.images:  # every texture must travel inside the FBX
    if im.users and not im.packed_file and im.source == "FILE":
        im.pack()
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
bpy.ops.export_scene.fbx(
    filepath=out, use_selection=False, global_scale=k,
    apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y",
    object_types={"MESH", "ARMATURE", "EMPTY"}, mesh_smooth_type="FACE",
    add_leaf_bones=False, bake_anim=False, path_mode="COPY", embed_textures=True)
meshes = [o.name for o in bpy.data.objects if o.type == "MESH"]
print(f"saved {out}: {os.path.getsize(out) / 1e6:.2f} MB, armature {arm.name}, meshes {meshes}, "
      f"images {[i.name for i in bpy.data.images if i.users]}")
