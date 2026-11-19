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

## Original missions (paused Nov 18 2026 to work on the hub zones)
First mission in progress: "Unstoppa-Invader!" (original m_1012: stage 1 = bay with 10 waves behind laser gates, stage 2 = boss arena with the warlord, adds, flame traps and health drops).
- Done (cloud tools, nothing uploaded yet):
  - `tools/unity_bundle_tree.py` prints any bundle's hierarchy, components and script fields; `tools/index_bundles.py` indexes the archive's 361 `Assets/Unrenamed` bundles by their contents (the popcorn minion, the shared transport FX, the warlord's FX and VO, doombots and the mission-complete music are in there).
  - `tools/export_scenario.py` scenario bundle -> JSON (every object, world transform, colliders, script fields); `tools/port_tile.py` tile or prop -> FBX built straight in Blender (baked lighting texture, Neon glow parts, collision triangles, mirrored variant `_M`, oversized meshes split); `tools/convert_scenario.py` mission XML + scenario JSON + en-us strings + tagged audio -> `studio/game/shared/MissionData.lua`; `tools/preview_stage.py` renders an assembled stage from the original camera (both stages checked).
  - `maps/tiles/`: the 12 SkrullShip tiles and props for both stages (FBX + JSON + previews).
  - `studio/game/shared/StageBuilder.lua` places tiles and props like ObjectPlaceholder, rebuilds tile collision as wedges, adds walls and laser gates (untested in Studio).
  - `Brawler.server.lua` has inert mission hooks (Config.Mission unset = the old wave run): crates, scenario events from impacts, sleeping spawns with aggro distance, shapeshifter, onKilled/onDespawn, `spawnEnemy(arch, i, at)`.
  - `heroes/InvaderPopcorn` (the minion: model + exact pack, not uploaded); `convert_game_data.py` has the Popcorn and Shifter archetypes and impact events (GameData.lua not regenerated yet).
- To resume: append the scenario runtime to the server (ports of ScenarioEventManager, SpawnController, SpawnGroup, CharacterSpawn, ColliderPopulationTrigger, ScenarioEventTransferBox, DisableObjectScenarioEvent, NewObjectiveScenarioEvent, ObjectSpawnRegion, ScenarioEventPeriodicEvent; the decompiled originals are in SHSUnderground/shso-unity-project `Assets/mainData/Assets/Scripts/*.cs`, blobless clone + `git cat-file`), a setup step that inserts the tile models into ServerStorage.SPSO.Tiles, the client objective banner and stage camera (CameraLiteSpring data is in MissionData), a sound sprite for the stage-complete jingle, ambience, crates, flames and boss VO, then upload and set Config.Mission.
- The original shapeshifters copy licensed heroes; the port maps them to evil copies of its own heroes (FORMS in convert_scenario.py).

## Hub zones (social spaces, current focus)
The original's four social zones are in the archive (`Assets/SocialSpace`): geometry bundles `daily_bugle2`, `baxter`, `Asgard`, `Villainville` (place them from their `<Zone>_Bundle` root, which holds the real layout) and scenario bundles `daily_bugle_geometry` (despite the name: the Daily Bugle scenario), `baxter_scenario`, `Asgard_scenario` (Villainville's scenario is not archived). The port renames the licensed places: Daily Bugle -> "Daily Bulletin" (zone id `Bulletin`), Baxter -> `Plaza`, Villainville -> `Villains`; Asgard stays.
- Pipeline: `port_zone.py <geometry.asset> out --name Zone --roots <Zone>_Bundle --skip <sky domes, lettering> --no-render boundary --remove obj:box:gold` -> FBX files + JSON; `export_scenario.py <scenario.asset> <Zone>_scenario.json <root>`; `port_hub_props.py` (unique interactive props, one port_tile export each) + `merge_props.py` (one props FBX per zone); `convert_hub.py` -> `studio/game/shared/HubData.lua` (ZONES in that file holds titles, offsets in the Roblox world, ambience and the replacement signs). Upload `maps/hub/*.fbx` (keys `hub_<file>`), then setup `02_hub` builds `workspace.SPSO_Hub.<Zone>`.
- Runtime: `Hub.server.lua` (zone arrival, fractals + hero tokens at the original spawn points, civilians on the original NPC paths, pigeons that take off, poke-to-jiggle props with star drops, door pairs, launchers: mission -> brawler, zones -> travel, shops "soon"), `HubClient.client.lua` (the original social camera booms, zone light, hub HUD and zone travel menu). The brawler client and server ignore heroes in hub zones; after a mission the players return to the start zone.
- Done: Daily Bulletin (geometry, props, civilians CivilianMale1-4/CivilianFemale1-4, Pigeon, Robber with exact packs). Exported but not uploaded: Plaza, Asgard and Villains geometry (`/home/claude/spso-port/zones/out`, regenerate with the commands above). Branding still to remove before upload: the Plaza's big "4" emblem on the tower and a "MARVEL" storefront sign; check Villains (DOOMletters, Doom_eye and the sky are skipped) and Asgard previews closely.
- Next for the hub: the other three zones (scenario + props + travel), zone music and ambience (one sound sprite: tracks/gameworld_* bundles and the zones' own SFX), the movement hotspots (fly / wall-crawl / ground-speed splines, teleport pads), the robber chase, emote zones, coin trees.

## Next
1. Hub zones (social spaces) and hub gameplay, porting their models (current focus, see above).
2. Resume the original missions (above), then more missions, enemies and bosses.
3. Hero overhaul (new designs) once everything is ported.
