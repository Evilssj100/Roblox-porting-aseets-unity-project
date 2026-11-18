# Roblox port workspace

Work for porting this game to Roblox. The original Unity project is untouched; everything new lives here.
Start with `HANDOFF.md`: it covers the current state, the 3-step update loop and every pipeline.

- `studio/`: everything that runs in Roblox.
  - `runtime/`: HeroPack (pack decoder) and ExactAnimator. ExactAnimator plays the original Unity animation curves exactly, using bones, or EditableMesh skinning when bones scale.
  - `game/`: the brawler. `shared/` holds config, net and the character animator; `server/Brawler`; `client/BrawlerClient`; `character/` holds Animate and Health overrides.
  - `setup/01_world.lua`: idempotent world setup (character templates, StarterCharacter, arena collision and spawns, lighting).
  - `manifest.json`, `SPSO_Package.rbxmx`, `unpack.lua`, `install.lua`: packaging and installing into Studio.
- `heroes/ElRugido/`: El Rugido, the first repurposed hero (original rig, mesh, weights and all 63 animations; new design).
  - `ElRugido.blend` and `textures/`: the Roblox-ready model and its textures (8 face-expression tiles).
  - `runtime/ElRugido.spsohero.b64`: runtime pack (original curves, mesh, bind data, self-tests). `ElRugido.pack.json` summarises it.
  - `variants/`: enemy costume recolors.
  - `roblox_data/`: per-frame skinning matrices, used for verification.
- `maps/OrbitalArena/`: the arena, Roblox-ready (`.blend`, upload-ready `.fbx`/`.glb`, preview).
- `tools/`: the pipeline scripts (bundle extraction, exact animation, hero packs, map prep, recolors, packaging).
