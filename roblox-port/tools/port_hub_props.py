"""Export the props of an original social-zone scenario (interactive objects, doors, launchers, coin trees,
fountain ripples...) as unique models with port_tile.py, and list every placed instance.

Instances are the outermost objects carrying an InteractiveObject / door script (or a static renderer of the FX
group). Identical instances (same meshes at the same local transforms) share one model; mirrored placements use
the mirrored variant. Indicator rings, gizmos and hotspot arrows are left out.

Usage: python port_hub_props.py <scenario.asset> <scenario.json> <out_dir> --zone Zone [--jobs 4]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_scenario import quat_mat  # noqa: E402
from spso_names import clean  # noqa: E402

ROOT_SCRIPTS = {"InteractiveObject", "DoorManager", "StoreDoorManager", "SnackDoorManager", "ArcadeDoorManager"}
SKIP_MESH = r"(?i)^(active_base|active_top|box02$|hotspot|hotspotmesh)"
TOOLS = os.path.dirname(os.path.abspath(__file__))


def world(o):
    m = np.eye(4)
    m[:3, :3] = quat_mat(o["rot"]) * np.array(o["scale"])
    m[:3, 3] = o["pos"]
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("scenario_json")
    ap.add_argument("out")
    ap.add_argument("--zone", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    d = json.load(open(a.scenario_json))
    objs = d["objects"]
    kids = {}
    for i, o in enumerate(objs):
        kids.setdefault(o["parent"], []).append(i)
    skip_mesh = re.compile(SKIP_MESH)

    def scripts(i):
        return {c.get("script") for c in objs[i]["components"] if c["type"] == "MonoBehaviour"}

    def renderers(i, acc):
        o = objs[i]
        if any(c.get("script") == "DestroyOnLoad" for c in o["components"]):
            return acc
        mf = next((c for c in o["components"] if c["type"] == "MeshFilter"), None)
        if mf and any(c["type"] == "MeshRenderer" for c in o["components"]):
            name = (mf.get("mesh") or {}).get("name") if isinstance(mf.get("mesh"), dict) else None
            if name and not skip_mesh.search(name):
                acc.append(i)
        for k in kids.get(i, []):
            renderers(k, acc)
        return acc

    roots = []
    claimed = set()

    def mark(i):
        claimed.add(i)
        for k in kids.get(i, []):
            mark(k)

    for i, o in enumerate(objs):  # outermost first (export order is depth-first)
        if i in claimed:
            continue
        if scripts(i) & ROOT_SCRIPTS or ("/ScenarioObjects/FX/" in o["path"] and
                                         any(c["type"] == "MeshRenderer" for c in o["components"])):
            if renderers(i, []):
                roots.append(i)
                mark(i)
    uniq, instances = {}, []
    for i in roots:
        W = world(objs[i])
        inv = np.linalg.inv(W)
        sig = []
        for r in renderers(i, []):
            mf = next(c for c in objs[r]["components"] if c["type"] == "MeshFilter")
            sig.append((mf["mesh"]["name"], tuple(np.round(inv @ world(objs[r]), 2).reshape(-1))))
        sig = tuple(sorted(sig))
        mirror = bool(np.linalg.det(W[:3, :3]) < 0)
        if sig not in uniq:
            base = re.sub(r"__collapsed$|_$", "", sig[0][0])
            name = clean(base)
            name = re.sub(r"[^A-Za-z0-9_]", "_", name[:1].upper() + name[1:])
            n, k = name, 2
            while n in {v["name"] for v in uniq.values()}:
                n, k = f"{name}_{k}", k + 1
            uniq[sig] = {"name": n, "path": objs[i]["path"], "variants": set()}
        u = uniq[sig]
        u["variants"].add(mirror)
        Wm = W @ np.diag([-1.0, 1, 1, 1]) if mirror else W
        sc = np.linalg.norm(Wm[:3, :3], axis=0)
        P = np.diag([1.0, 1, -1])
        R = P @ (Wm[:3, :3] / sc) @ P
        instances.append({"prop": u["name"] + ("_M" if mirror else ""), "oid": i, "scale": round(float(sc.mean()), 5),
                          "cf": [round(float(v), 4) for v in P @ W[:3, 3] * 2.56] + [round(float(v), 6) for v in R.reshape(-1)],
                          "scripts": sorted(s for s in scripts(i) if s), "name": clean(objs[i]["name"])})
    os.makedirs(a.out, exist_ok=True)
    jobs = []
    for u in uniq.values():
        for mirror in sorted(u["variants"]):
            out_name = f"{a.zone}_{u['name']}"
            cmd = [sys.executable, os.path.join(TOOLS, "port_tile.py"), a.bundle, "-", a.out, "--path", u["path"],
                   "--name", out_name, "--skip-mesh", SKIP_MESH, "--no-preview"] + (["--mirror"] if mirror else [])
            jobs.append((out_name + ("_M" if mirror else ""), cmd))

    def run(job):
        name, cmd = job
        r = subprocess.run(cmd, capture_output=True, text=True)
        line = next((ln for ln in r.stdout.splitlines() if "parts=" in ln), r.stderr.strip().splitlines()[-1:] or ["?"])
        return name, r.returncode, line if isinstance(line, str) else line[0]

    with ThreadPoolExecutor(a.jobs) as ex:
        for name, rc, line in ex.map(run, jobs):
            print(("OK " if rc == 0 else "FAILED ") + line[:160])
    for inst in instances:
        inst["prop"] = f"{a.zone}_{inst['prop']}"
    manifest = {"zone": a.zone, "props": sorted({j[0] for j in jobs}), "instances": instances}
    json.dump(manifest, open(os.path.join(a.out, f"{a.zone}_props.json"), "w"), indent=0)
    print(f"{a.zone}: {len(instances)} instances, {len(uniq)} unique props, {len(jobs)} models")


if __name__ == "__main__":
    main()
