"""Port heroes to Roblox in bulk, cloud only (no Studio or Blender session needed). Per hero:

  base     run_hero_base steps: unity_hero_anim_exact.py, unity_hero_to_blend_exact.py, uv_bake_maps.py
  look     repurpose_heroes.py (texture recipe) + apply_hero_textures.py   -> <work>/out/<H>/<H>.blend, previews
  prep     prep_roblox_hero.py           -> heroes/<H>/<H>.blend, textures/<H>_Body.png + _Face_0..7.png, <H>_meta.json
  mesh     export_roblox_skin_data.py    -> <work>/<H>/roblox/mesh.bin  (MESH_ONLY)
  pack     spso_hero_pack.py --exact     -> heroes/<H>/runtime/<H>.spsohero(.b64) + <H>.pack.json (checked vs exact)
  fbx      export_hero_fbx.py            -> heroes/<H>/<H>.fbx  (upload-ready, textures embedded)

A step is skipped when its outputs are newer than its inputs, so a re-run only redoes what changed.

Usage: python port_hero.py [--work DIR] [--repo DIR] [--jobs 2] [--force] Hero [Hero ...]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

TOOLS = os.path.dirname(os.path.abspath(__file__))
# new hero -> source bundle at the repo root (ElRugido was built by hand with repaint/build_el_rugido.py)
HEROES = {"Skyvolt": "Falcon_01-darkhawk", "Aurora": "Ms_Marvel_01-classic",
          "Magmaul": "Thing_01-classic", "NightGecko": "spiderman-secretwars"}


def mtime(p):
    return os.path.getmtime(p) if os.path.exists(p) else None


def fresh(outs, ins):
    to = [mtime(p) for p in outs]
    ti = [mtime(p) for p in ins if mtime(p) is not None]
    return all(t is not None for t in to) and (not ti or min(to) >= max(ti))


def port(hero, a):
    W, O = os.path.join(a.work, hero), os.path.join(a.work, "out", hero)
    D = os.path.join(a.repo, "roblox-port", "heroes", hero)
    bundle = os.path.join(a.repo, HEROES[hero] + ".unity3d")
    py = [sys.executable]
    T = lambda s: os.path.join(TOOLS, s)  # noqa: E731
    anim, exact = os.path.join(W, "anim"), os.path.join(W, f"{hero}_exact.blend")
    body, atlas = os.path.join(O, f"{hero}_Body.png"), os.path.join(O, f"{hero}_HeadAtlas.png")
    mesh = os.path.join(W, "roblox", "mesh.bin")
    steps = [
        ("base", [anim + ".npz", exact], [bundle],
         [py + [T("unity_hero_anim_exact.py"), bundle, anim],
          py + [T("unity_hero_to_blend_exact.py"), bundle, anim, exact],
          py + [T("uv_bake_maps.py"), exact, os.path.join(W, "maps")]], {}),
        ("look", [os.path.join(O, f"{hero}.blend"), body, atlas], [exact],
         [py + [T("repurpose_heroes.py"), a.work, os.path.join(a.work, "out"), hero],
          py + [T("apply_hero_textures.py"), exact, hero, body, atlas, os.path.join(O, f"{hero}.blend"),
                os.path.join(O, f"{hero}_preview.png")]], {}),
        ("prep", [os.path.join(D, f"{hero}.blend"), os.path.join(D, "textures", f"{hero}_Face_7.png")],
         [os.path.join(O, f"{hero}.blend"), atlas, body, T("prep_roblox_hero.py")],
         [py + [T("prep_roblox_hero.py"), os.path.join(O, f"{hero}.blend"), atlas, D, hero, body]], {}),
        ("mesh", [mesh], [os.path.join(D, f"{hero}.blend")],
         [py + [T("export_roblox_skin_data.py"), os.path.join(D, f"{hero}.blend"), anim,
                os.path.join(D, "textures"), os.path.dirname(mesh), str(a.studs)]], {"MESH_ONLY": "1"}),
        ("pack", [os.path.join(D, "runtime", f"{hero}.spsohero.b64")], [mesh, bundle, T("spso_hero_pack.py")],
         [py + [T("spso_hero_pack.py"), bundle, mesh, hero, os.path.join(D, "runtime"), "--studs", str(a.studs),
                "--exact", anim]], {}),
        ("fbx", [os.path.join(D, f"{hero}.fbx")], [os.path.join(D, f"{hero}.blend")],
         [py + [T("export_hero_fbx.py"), os.path.join(D, f"{hero}.blend"), os.path.join(D, f"{hero}.fbx"), str(a.studs)]], {}),
    ]
    os.makedirs(W, exist_ok=True)
    done = []
    for name, outs, ins, cmds, env in steps:
        if not a.force and fresh(outs, ins):
            continue
        t0 = time.time()
        with open(os.path.join(W, f"port_{name}.log"), "w") as log:
            for c in cmds:
                r = subprocess.run(c, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **env}, cwd=W)
                if r.returncode:
                    return hero, done + [f"{name} FAILED (see {log.name})"], None
        done.append(f"{name} {time.time() - t0:.0f}s")
    rig = os.path.join(D, f"{hero}_rig.npz")  # sampling scratch from prep, not needed in the repo
    if os.path.exists(rig):
        shutil.move(rig, os.path.join(W, f"{hero}_rig.npz"))
    prev = os.path.join(O, f"{hero}_preview.png")
    if os.path.exists(prev):
        shutil.copy2(prev, os.path.join(D, f"{hero}_preview.png"))
    pj = os.path.join(D, "runtime", f"{hero}.pack.json")
    info = json.load(open(pj)) if os.path.exists(pj) else None
    return hero, done, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("heroes", nargs="*")
    ap.add_argument("--work", default="/home/claude/spso-port/work/heroes")
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(TOOLS, "..", "..")))
    ap.add_argument("--studs", type=float, default=2.56)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    heroes = a.heroes or list(HEROES)
    with ThreadPoolExecutor(a.jobs) as ex:
        for hero, done, info in ex.map(lambda h: port(h, a), heroes):
            chk = (info or {}).get("checkVsExact", {})
            print(f"{hero:11s} {', '.join(done) or 'up to date'}" + (
                f" | clips {len(info['clips'])}, bones {len(info['bones'])}, {info['zstdBytes'] / 1e6:.2f} MB, "
                f"matrix err {chk.get('maxMatrixError', float('nan')):.2e}, vertex err {chk.get('maxVertexErrorStuds', float('nan')):.2e} studs"
                if info else ""), flush=True)


if __name__ == "__main__":
    main()
