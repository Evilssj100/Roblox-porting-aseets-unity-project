# Roblox port workspace

Work for porting this game to Roblox. The original Unity project is untouched; everything new lives here.

- `heroes/ElRugido/`: El Rugido, the first repurposed hero (original brute rig, mesh, weights and all 63 animations; new design).
  - `ElRugido.blend`: Roblox-ready Blender file (Blender 5.x, 60 fps). Body and head are separate meshes, and the head uses face tile 0.
  - `textures/`: body texture and the 8 face-expression tiles (0 Normal, 1 Happy, 2 Surprised, 3 Aggressive, 4 Squint, 5 Blink, 6 Custom1, 7 Custom2).
  - `ElRugido_anim_exact.json`: clip list with durations, sample counts and the original animation events (face tags, hitbox windows, combo windows, footsteps).
- `tools/`: the pipeline scripts (Unity bundle extraction, exact 60 fps animation sampling, Blender builders, checks).

Animations are exact: Blender playback matches the original skinning within 1e-5 units on every clip, including bone scaling.
