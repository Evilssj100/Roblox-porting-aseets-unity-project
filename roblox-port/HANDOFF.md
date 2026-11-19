You're taking over the Roblox port of my game: my fork Evilssj100/Roblox-porting-aseets-unity-project (a Unity 3.5 remake of Super Hero Squad Online). All port work lives on the `roblox-port` branch, folder `roblox-port/`. Attach the repo and clone that branch (shallow is fine).

## Rules
- Keep every animation exactly as it is, and each character's body, rig, skin weights and proportions.
- No Marvel names, logos or branding in anything that is uploaded or ships in scripts (tools/spso_names.py cleans and checks names).
- Heroes: the five playable heroes have repurposed looks. A full hero overhaul (new designs) comes after everything is ported. Characters taken from the archive are ported with their ORIGINAL look for now ("don't worry about recolouring yet").
- Never print, log or ask for my Roblox API key (my Blender's Roblox Uploader add-on holds it).
- In my Blender, never touch my own scenes or unsaved work and never run exports there (it crashed once). Only download files and upload them.
- Commit and push only to `roblox-port`.

## State (Nov 18 2026)
Place "11032026_2" (placeId 104298000827208). The brawler is playable end to end:
- **Heroes (hero select with live animated previews):** El Rugido, Skyvolt, Aurora, Magmaul, Night Gecko. Every clip plays EXACTLY (ExactAnimator evaluates the original Hermite curves; Studio self-test 4e-7 to 8e-7 on all five packs).
- **Combat from the original data (GameData.lua, generated):** L1-L5 chain, R1-R3 power attacks (20/40/60 power), super (100). Impacts are timed by the clips' own AnimationEvents. Melee colliders are spheres on the exact bones; there are projectiles, beams, target impacts, recoil types (small/big/getup/knockdown/launch/stun), pushback and launch, power from damage dealt and received, combo heat, KO scoring with survival bonus and medals (the original ScoreCalculator formula), pickups.
- **Enemies:** the original invader soldiers (melee brawler, rifle gunner, bazooka, grenadier) and the warlord boss (teleport strike), with their own models, clips, colliders, impacts and the shared character effects. Five waves, each with the original stage music, then the mission complete screen.
- **Effects and sounds:** every hero effect sequence (particles, trails, lights, beams, FX meshes) is rebuilt on the bones by FxPlayer. All sounds (hero, impact, UI, music) come from uploaded sound sprites.
- **GUI:** loading screen, hero select, the original brawler HUD art (player frame with live portrait, life bar, power stars, boss bar, enemy bars, medals, damage glow, GO arrow, mission complete), damage numbers, target ring, shadows.
- **Map:** workspace.OrbitalArena (the original boss arena, emblem covered).

## Asset ids
`studio/assets.json` holds every uploaded id (key -> asset id); `tools/record_uploads.py` turns it into `studio/game/shared/Assets.lua`, the only place ids live in code. Code package 113546958541177, arena model 96857863111637. Each character model has a model asset and a data package (its runtime pack), inserted by the setup step.

## Update loop (cheap way to change game code)
1. Edit `roblox-port/studio/**`, then `python roblox-port/tools/build_studio_manifest.py roblox-port && python roblox-port/tools/build_rbxmx_package.py roblox-port <label>`. Commit, push, note the sha.
2. Blender MCP: `result = bpy.app.driver_namespace["spso_upload_package"]("<sha>")` (PATCHes the code package).
3. Studio MCP (Edit): `return require(game.ServerStorage.SPSO.Tools.Unpack:Clone())(113546958541177)`, then if models or packs changed `require(game.ServerStorage.SPSO.Setup["01_world"]:Clone())()` (idempotent: inserts missing models, unpacks changed data packages, builds templates).

## Bulk uploads (models, images, sound sprites, data packages)
`python roblox-port/tools/stage_assets.py roblox-port <fx_work_dir> <unity Assets dir>` writes `studio/upload/jobs.json` (everything not yet in assets.json). Push, then in Blender run `bpy.app.driver_namespace["spso_upload_jobs"]("<sha>")` (runs in a background thread, 3 at a time). Poll `bpy.app.driver_namespace["spso_bulk"]` (done/total/results/errors). Save `results` to a JSON file and run `python roblox-port/tools/record_uploads.py roblox-port results.json`. If the helpers are missing after a Blender restart, paste `tools/blender_helpers.py` into the Blender MCP once.

## Pipelines (tools in roblox-port/tools; Python 3.13 with UnityPy, numpy, Pillow, scipy, zstandard, bpy==5.2.3, ffmpeg)
- **Characters in bulk:** `python port_hero.py <Name> ...` runs base (exact animation extraction + exact Blender build), look (repurposed textures, or the original look for ORIGINALS), prep, mesh, pack (checked against the exact extraction, ~5e-6) and FBX. Steps are skipped when up to date. Add a hero to HEROES (bundle at the repo root) or ORIGINALS (character bundle name in the SHSO archive).
- **SHSO archive:** github.com/SHSUnderground/shso-archive-structured has the whole original game: 362 character bundles, 183 brawler tiles, 255 mission scenarios, social zones, GUI, FX and audio bundles (UnityPy reads them; unity_mesh_compat.py handles their Unity 3.2 meshes). Clone it blobless (`git clone --filter=blob:none --no-checkout --depth 1`) and fetch single files with `git cat-file -p HEAD:Assets/<path>`. Do NOT run `git ls-tree --long` on it: that downloads every blob. Also there: shso-unity-project, shso-server, shso-archive.
- **Game data:** `python convert_game_data.py <data_xml_dir> roblox-port` writes GameData.lua (heroes, enemy archetypes and their models, scoring). The XML comes from Assets/Data-general.asset (980 TextAssets).
- **Effects and sounds:** `python build_fx.py roblox-port <work> Hero=bundle ... Shared=<shared_character_fx> --ui-sounds ... --audio-bundles ...` writes FxData.lua, effect textures and sound sprites (each under 6.5 minutes).
- **Maps:** unity_yaml_scene_to_glb.py, then env_glb_to_blend.py, then prep_roblox_arena.py. The archive's brawler tiles and scenarios are the next maps to port.
- **Runtime (Luau):** HeroPack, ExactAnimator (Play/CrossFade/GetState/Event/NodeCFrame/SelfTest), FxPlayer, Sound, CharacterAnimator.

## Gotchas
- The Studio Assistant can't reach GitHub (HTTP allowlist), and its uploads only accept approved folders, so everything reaches Studio as uploaded packages (rbxmx) inserted with InsertService.
- StringValue: at most 199,999 characters and not binary-safe, so packs are base64 chunks.
- EditableMesh and EditableImage share a small memory budget: exact skinning only for the local hero.
- Decals can't multiply: the shadow uses an alpha copy (gui_ShadowAlpha).
- Newly uploaded images show "No asset content representation found" until moderation approves them.
- `_G` is not shared with the Studio Assistant's execute_luau; read game state from attributes instead.
- Roblox audio uploads are limited per month; keep sounds in sprites.

## Next
1. Port the original missions: the archive's brawler scenarios (tile layouts, spawners, triggers) and tiles (SkrullShip, Rooftops, Sewers, Subway, Factory, Asgard...), then the social zones and more enemies and bosses.
2. Hero overhaul (new designs) once everything is ported.
