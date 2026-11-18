"""Stage every file that has to become a Roblox asset and write the upload job list.

  assets/fx/*.png            effect textures (from build_fx.py)
  assets/audio/*.ogg         the sound sprite (every hero sound, UI sound and music track in one file)
  assets/gui/*.png           the original GUI art that carries no branding (targeting rings, frames, panels,
                             loading backgrounds, class icons), renamed through spso_names
  assets/skins/*.png         rival costume recolours for enemy archetypes
  heroes/<H>/<H>.fbx, heroes/<H>/textures/<H>_Face_1..7.png, studio/packages/Hero_<H>.rbxmx
studio/upload/jobs.json lists every key that is not yet in studio/assets.json (key -> Roblox asset id).
The Blender helper (HANDOFF.md, "Bulk uploads") downloads each file at a commit and POSTs it; then
record_uploads.py stores the ids and regenerates studio/game/shared/Assets.lua.

Usage: python stage_assets.py <roblox-port dir> <fx_work_dir> <unity Assets dir>
"""
import colorsys
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spso_names import check, clean  # noqa: E402

GUI = [  # original GUI art without logos or licensed characters (checked on a contact sheet)
    "Resources/enemyselected_ring.png", "Resources/enemyselected_arrows.png", "Resources/gui/targeting/selection_ring.png",
    "Resources/gui/targeting/reticule_outer_diff_tex.png", "Resources/gui/targeting/reticule_inner_diff_tex.png",
    "Resources/gui/targeting/targeting_diff_tex.png", "Resources/ui_target_tex.png",
    "Resources/gui/mouseover_3d/player_move/move_marker.png", "Resources/ring_sharp_additive_tex.png", "Resources/Shadow.png",
    "Resources/gui/hotspots/chubbyarrow_diff_tex.png", "Resources/gui/notifications/baseWindow.png",
    "Resources/gui/notifications/popup_icon_burst.png", "Resources/gui/notifications/invitation_frame_left.png",
    "Resources/gui/notifications/herobg.png", "Resources/gui/loading/loading_bar_frame.png",
    "Resources/gui/loading/loading_bar_fill.png", "Resources/gui/loading/loading_bar_rightside.png",
    "Resources/gui/loading/loading_star.png", "Resources/gui/loading/loading_tipbox_leftside.png",
    "Resources/gui/loading/loading_tipbox_rightside.png", "Resources/gui/loading/preloading_blue_backdrop.png",
    "Resources/gui/loading/mshs_loading_background_01.png", "LoginAssets/background_1_login_screen.png",
    "LoginAssets/background_2_login_screen.png", "LoginAssets/login_background_panel.png", "LoginAssets/light_rays_top_layer.png",
    "Resources/gui/loading/welcome/mshs_central_content_panel_bg.png",
    "Resources/gui/loading/welcome/mshs_central_content_panel_speechbubble.png",
    "Resources/gui/loading/background/0.png", "Resources/gui/loading/background/1.png", "Resources/gui/loading/background/2.png",
    "Resources/gui/loading/background/4.png", "Resources/gui/loading/background/5.png", "Resources/gui/loading/background/6.png",
    "Resources/gui/symbols/animal_icon.png", "Resources/gui/symbols/elemental_icon.png", "Resources/gui/symbols/energy_icon.png",
    "Resources/gui/symbols/speed_icon.png", "Resources/gui/symbols/strength_icon.png", "Resources/gui/symbols/tech_icon.png",
]
RIVALS = {"NightGecko": 0.42, "Magmaul": 0.55}  # enemy costume: hue rotation of the hero's look


def gui_key(path):
    parts = path.replace("\\", "/").split("/")
    base = os.path.splitext(parts[-1])[0]
    if parts[-2] == "background":
        base = f"loading_background_{base}"
    return "gui_" + clean(base).replace(" ", "_").replace("game_", "")


def hue_shift(im, shift):
    a = np.asarray(im.convert("RGBA")).astype(np.float32) / 255
    rgb = a[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn + 1e-9
    h = np.where(mx == rgb[..., 0], ((rgb[..., 1] - rgb[..., 2]) / d) % 6,
                 np.where(mx == rgb[..., 1], (rgb[..., 2] - rgb[..., 0]) / d + 2, (rgb[..., 0] - rgb[..., 1]) / d + 4)) / 6
    s = np.where(mx > 0, d / (mx + 1e-9), 0)
    h = (h + shift) % 1.0
    out = np.zeros_like(rgb)
    hsv = np.stack([h, s, mx], -1).reshape(-1, 3)
    out = np.array([colorsys.hsv_to_rgb(*p) for p in hsv]).reshape(rgb.shape)
    return Image.fromarray((np.concatenate([out, a[..., 3:]], -1) * 255 + 0.5).astype(np.uint8))


def main():
    port, fx, unity = sys.argv[1:4]
    A = os.path.join(port, "assets")
    for d in ("fx", "gui", "audio", "skins"):
        os.makedirs(os.path.join(A, d), exist_ok=True)
    jobs = []
    have = json.load(open(os.path.join(port, "studio", "assets.json"))) if os.path.exists(os.path.join(port, "studio", "assets.json")) else {}

    def job(key, rel, kind, name):
        check(key + name, "asset name")
        if key not in have:
            ctype = {"image": "image/png", "model": "model/fbx", "package": "model/x-rbxm", "audio": "audio/ogg"}[kind]
            jobs.append({"key": key, "path": f"roblox-port/{rel}", "kind": kind, "name": name[:50], "ctype": ctype})

    man = json.load(open(os.path.join(fx, "fx_manifest.json")))
    for t in man["textures"]:
        shutil.copy2(os.path.join(fx, t["file"]), os.path.join(A, "fx", t["key"] + ".png"))
        job(t["key"], f"assets/fx/{t['key']}.png", "image", t["key"])
    shutil.copy2(os.path.join(fx, man["sprite"]["file"]), os.path.join(A, "audio", "spso_sound_sprite.ogg"))
    job("sound_sprite", "assets/audio/spso_sound_sprite.ogg", "audio", "SPSO Sound Sprite")
    for g in GUI:
        k = gui_key(g)
        im = Image.open(os.path.join(unity, g)).convert("RGBA")
        if max(im.size) > 1024:
            im.thumbnail((1024, 1024), Image.LANCZOS)
        im.save(os.path.join(A, "gui", k + ".png"))
        job(k, f"assets/gui/{k}.png", "image", k)
    for hero, shift in RIVALS.items():
        for part, src in (("Body", f"heroes/{hero}/textures/{hero}_Body.png"), ("Head", f"heroes/{hero}/textures/{hero}_Face_0.png")):
            k = f"skin_{hero}_Rival_{part}"
            hue_shift(Image.open(os.path.join(port, src)), shift).save(os.path.join(A, "skins", k + ".png"))
            job(k, f"assets/skins/{k}.png", "image", k)
    for hero in sorted(os.listdir(os.path.join(port, "heroes"))):
        d = os.path.join(port, "heroes", hero)
        if os.path.exists(os.path.join(d, f"{hero}.fbx")):
            job(f"model_{hero}", f"heroes/{hero}/{hero}.fbx", "model", hero)
            for i in range(1, 8):
                job(f"face_{hero}_{i}", f"heroes/{hero}/textures/{hero}_Face_{i}.png", "image", f"{hero}_Face_{i}")
        if os.path.exists(os.path.join(port, "studio", "packages", f"Hero_{hero}.rbxmx")):
            job(f"package_{hero}", f"studio/packages/Hero_{hero}.rbxmx", "package", f"SPSO Hero Data {hero}")
    os.makedirs(os.path.join(port, "studio", "upload"), exist_ok=True)
    json.dump(jobs, open(os.path.join(port, "studio", "upload", "jobs.json"), "w"), indent=0)
    kinds = {}
    for j in jobs:
        kinds[j["kind"]] = kinds.get(j["kind"], 0) + 1
    print(f"{len(jobs)} uploads queued: {kinds}")


if __name__ == "__main__":
    main()
