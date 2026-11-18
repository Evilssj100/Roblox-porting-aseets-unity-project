You're taking over the Roblox port of my game: my fork Evilssj100/Roblox-porting-aseets-unity-project (a Unity 3.5 remake of Super Hero Squad Online). All port work lives on the `roblox-port` branch, folder `roblox-port/`. Attach the repo and clone that branch (shallow is fine).

## Rules
- Repurpose the heroes, don't recreate them: keep each hero's body, rig, skin weights and proportions so the original animations still fit, and keep every animation exactly as it is.
- Rework whatever identifies the Marvel character (costume, colors, emblem, mask, markings, props, name) so every finished hero is an original character. No Marvel names, logos or branding anywhere (maps too). Keep the game's own style. No gray boxes.
- Never print, log or ask for my Roblox API key (my Blender's Roblox Uploader add-on holds it).
- In my Blender, never touch my own scenes or unsaved work and never run exports there (it crashed once). Only download files and upload them.
- Commit and push only to `roblox-port`.

## State (Nov 18 2026): the brawler runs in Studio
Place "11032026_2" (placeId 104298000827208), saved as version 22:
- **Map:** workspace.OrbitalArena, the original boss arena. It's renamed, the alien emblem is covered by an original star medallion, and it keeps its baked lighting textures. Collision is invisible primitive parts (Collision folder: floor plus 12 walls), and Spawns holds the spawn markers. Model asset 96857863111637.
- **Hero:** El Rugido is the StarterCharacter: a Humanoid plus HumanoidRootPart driving the skinned rig, with templates in ServerStorage.SPSO.Characters. His animation is EXACT. ExactAnimator evaluates the original Unity Hermite curves at every frame. When the pose has no bone scale it drives the Roblox bones; while a clip scales bones (fists swelling) it switches to EditableMesh CPU skinning, local hero only.
  - Verified in Studio: self-test 7.6e-7 across all 63 clips including off-grid times; bone path 0.000006 studs.
- **Game:** ServerScriptService.SPSO.Brawler and StarterPlayerScripts.BrawlerClient.
  - Combat uses the original attack chains (L1–L5, R1–R3, super), with hit windows and chain windows taken from the clips' own AnimationEvents (OnCollisionEnable/Disable, OnChainAttack).
  - Reactions: recoil_small, recoil_big, launch, getup and KO.
  - Faces swap on OnFaceAnimTag following FacialAnimation.cs. Root motion follows performRootMotion.
  - Enemies are rival luchadores (El Rugido with 4 costume recolors) with simple AI. The game runs 5 waves, then victory and restart, with a power meter and super.
  - The camera is the fixed brawler camera. The HUD has health, power, wave, damage numbers and enemy health bars. Emotes are on keys 1–4.
- **Package asset 113546958541177:** all scripts plus the hero pack data. Re-uploaded (PATCH) on every update.

## Update loop (3 tool calls, the cheap way to change anything)
1. Edit files under `roblox-port/studio/`, then run:
   `python roblox-port/tools/build_studio_manifest.py roblox-port && python roblox-port/tools/build_rbxmx_package.py roblox-port <label>`
   Then commit and push, and note the commit sha.
2. Blender MCP (uses the add-on's key; downloads, then PATCHes the package asset). If the helper below is missing after a Blender restart, define it once:
   ```python
   import bpy, os, sys, urllib.request, tempfile
   def spso_upload_package(commit, asset_id="113546958541177"):
       m = sys.modules["roblox_uploader"]; p = m._prefs()
       path = os.path.join(tempfile.gettempdir(), "spso_rbx", "package", "SPSO_Package.rbxmx"); os.makedirs(os.path.dirname(path), exist_ok=True)
       urllib.request.urlretrieve(f"https://raw.githubusercontent.com/Evilssj100/Roblox-porting-aseets-unity-project/{commit}/roblox-port/studio/SPSO_Package.rbxmx", path)
       job = {"method": "PATCH", "url": f"{m.API}/assets/{asset_id}", "path": path, "ctype": "model/x-rbxm", "asset_id": asset_id,
              "request": {"assetType": "Model", "assetId": asset_id, "creationContext": {"creator": m._creator(p)}}}
       aid, mod = m._run_one(job, m._key(p)); return {"assetId": aid, "moderation": mod}
   bpy.app.driver_namespace["spso_upload_package"] = spso_upload_package
   result = spso_upload_package("<sha>")
   ```
3. Studio MCP (Edit): `return require(game.ServerStorage.SPSO.Tools.Unpack:Clone())(113546958541177)`. To run the world setup again, which is idempotent: `require(game.ServerStorage.SPSO.Setup["01_world"]:Clone())()`.

Other uploads (models, images) also go through the add-on's `_run_one` with the same kind of job dict. Use POST for new assets; for images use `assetType "Image"` and `ctype image/png`. Studio inserts with `InsertService:LoadAsset(id)`.

## Pipelines (tools in roblox-port/tools; Python 3.13 with UnityPy, numpy, Pillow, zstandard, scipy, bpy==5.2.3)
- **Hero animation data:** unity_hero_anim_exact.py (bundle → exact 60 fps npz/json, for checking).
  - `spso_hero_pack.py <bundle> <mesh.bin> <Hero> <out> --exact <prefix>` writes the runtime pack. It holds the original curve keys in Roblox space, plus mesh, bind data and self-tests, as zstd + base64.
  - `spso_pack_read.py` is the reference decoder and evaluator.
  - mesh.bin comes from export_roblox_skin_data.py, run on the Roblox-ready hero .blend from prep_roblox_hero.py.
- **Hero repaint (original look):** uv_bake_maps.py → repaint_<hero>.py → build_<hero>.py → prep_roblox_hero.py. Upload the model and textures with the add-on, at fbx_scale 2.56 studs per unit.
- **Enemy variants:** recolor_variants.py (offline hue shift of the costume), then upload the results as images. Don't recolor at runtime: the EditableImage budget runs out.
- **Maps:** unity_yaml_scene_to_glb.py → env_glb_to_blend.py → `prep_roblox_arena.py <blend> <out> <Map>`.
  - prep_roblox_arena.py renames the map, covers emblems with a medallion, keeps the baked UV as the only UV set, scales to studs, puts the floor at 0, triangulates, and writes the FBX and GLB.
  - Upload the FBX. In Studio, setup orients it with the back wall at -Z.
- **Runtime (Luau):** studio/runtime/HeroPack.lua and ExactAnimator.lua. The ExactAnimator API mirrors Unity's legacy Animation component: Play, CrossFade, Stop, Rewind, GetState (time, speed, wrapMode), the Event signal, ConsumeRootMotion, SetFace, SetPartTexture, and SelfTest(pack).

## Gotchas learned
- The Studio Assistant can't reach GitHub (HTTP allowlist), and its uploads only accept approved folders. That's why the package goes through Blender. If I add raw.githubusercontent.com to the Assistant HTTP allowlist, `studio/install.lua` can install straight from GitHub instead.
- StringValue: at most 199,999 characters and not binary-safe, so hero packs are stored as base64 chunks.
- EditableMesh and EditableImage share a small per-device memory budget. Keep exact skinning to the local hero, and free meshes on Destroy.
- A convex decomposition of a bowl-shaped collision mesh fills the bowl, so build collision from parts instead.
- The FBX import maps Blender +Y to Roblox +Z. Mirrored source objects (scale -1) need flipped normals.
- The first Open Cloud FBX upload of the arena failed with "Unknown Error". It worked after triangulating and giving every mesh a UV set and a material.

## Next
1. Repurpose the other four heroes (Falcon_01-darkhawk, Ms_Marvel_01-classic, Thing_01-classic, spiderman-secretwars) into original characters, show me renders, then run the same pipeline. Hero select comes after that.
2. Port more of the original game around the brawler (the behaviour scripts are in Assets/mainData/Assets/Scripts: BehaviorAttackBase, CharacterMotionController, BehaviorMovement and others).
