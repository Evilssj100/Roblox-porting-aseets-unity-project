# Roblox port workspace

Work for porting this game to Roblox. The original Unity project is untouched; everything new lives here.
Start with `HANDOFF.md`: it covers the current state, the 3-step update loop and every pipeline.

- `studio/`: everything that runs in Roblox.
  - `runtime/`: HeroPack (pack decoder) and ExactAnimator. ExactAnimator plays the original Unity animation curves exactly, using bones, or EditableMesh skinning when bones scale.
  - `game/`: the brawler. `shared/` holds GameConfig, GameData (generated), FxData (generated), Assets (generated), Net, Sound, FxPlayer and the character animator; `server/Brawler`; `client/BrawlerClient`.
  - `setup/01_world.lua`: idempotent world setup (character templates, StarterCharacter, arena collision and spawns, lighting).
  - `manifest.json`, `SPSO_Package.rbxmx`, `unpack.lua`, `install.lua`: packaging and installing into Studio.
- `heroes/<Name>/`: every character model: the five playable heroes (El Rugido, Skyvolt, Aurora, Magmaul, Night Gecko; repurposed looks) and the invader enemies and warlord boss (original looks, from the SHSO archive). Each has the Roblox-ready `.blend` and `.fbx`, `textures/` (body and 8 face-expression tiles) and `runtime/<Name>.spsohero.b64` (original curves, mesh, bind data, self-tests).
- `assets/`: effect textures, GUI art and the sound sprites, staged for upload. `studio/assets.json` maps every key to its Roblox asset id.
- `maps/OrbitalArena/`: the arena, Roblox-ready (`.blend`, upload-ready `.fbx`/`.glb`, preview).
- `tools/`: the pipeline scripts: `port_hero.py` (characters in bulk), `convert_game_data.py` (original XML data), `build_fx.py` (effects and sounds), `stage_assets.py` / `record_uploads.py` (bulk uploads and asset ids), `blender_helpers.py` (upload helpers to paste into Blender), plus bundle extraction, exact animation, map prep and packaging.
