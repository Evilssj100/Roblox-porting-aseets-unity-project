"""Original social zones -> studio/game/shared/HubData.lua: per zone the placed geometry (port_zone.py JSON),
the props and their instances (port_hub_props.py + merge_props.py), player start points, the social camera
booms, ambient colour, fractals, hero tokens, pigeons, civilian paths and spawns, game launchers, doors,
music zones and the replacement signs, all in Roblox space (studs, Roblox axes) plus the zone's world offset.

Usage: python convert_hub.py <roblox-port dir> <hub_dir> <zones_dir> Zone [Zone ...]
  hub_dir: <Zone>_scenario.json, <Zone>_Props.json, props/<Zone>_props.json;  zones_dir: out/<Zone>.json
"""
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_scenario import cf, lua, quat_mat  # noqa: E402
from spso_names import check, clean  # noqa: E402

K = 2.56
P = np.diag([1.0, 1, -1])
# the port's zone names (the originals are licensed names) and where each zone sits in the Roblox world
ZONES = {
    "Bulletin": {"title": "Daily Bulletin", "order": 1, "offset": [6000, 0, 0], "ambience": "Amb_BaseLayer_SHC_Streets",
                   "signs": [{"text": "DAILY BULLETIN", "center": [169.8, 32.18, -59.88], "size": [27.0, 3.6], "normal": [0, 0, 1]},
                             {"text": "DAILY BULLETIN", "center": [169.84, 4.18, -60.53], "size": [9.9, 1.7], "normal": [0, 0, 1]}]},
}
CHARACTERS = ["CivilianMale1", "CivilianMale2", "CivilianMale3", "CivilianMale4", "CivilianFemale1", "CivilianFemale2",
              "CivilianFemale3", "CivilianFemale4", "HubPigeon", "Robber"]
CIVILIANS = {f"npc_{g}_0{i}": f"Civilian{g.capitalize()}{i}" for g in ("male", "female") for i in range(1, 5)}
LAUNCHERS = {"brawler": "mission", "card": "cardgame", "hq": "hq", "worldmap": "zones"}


def pos(p, off):
    return [round(float(v), 3) for v in P @ np.array(p) * K + np.array(off)]


def zone_cf(o, off):
    c = cf(o["pos"], quat_mat(o["rot"]))
    return [round(c[0] + off[0], 4), round(c[1] + off[1], 4), round(c[2] + off[2], 4)] + c[3:]


def main():
    root, hub_dir, zones_dir = sys.argv[1:4]
    zones, props = {}, {}
    for Z in sys.argv[4:]:
        zc = ZONES[Z]
        off = zc["offset"]
        sc = json.load(open(os.path.join(hub_dir, f"{Z}_scenario.json")))
        objs = sc["objects"]
        by_path = {o["path"]: i for i, o in enumerate(objs)}

        def mbs(script):
            for i, o in enumerate(objs):
                for c in o["components"]:
                    if c.get("script") == script:
                        yield i, o, c["fields"]
        geo = json.load(open(os.path.join(zones_dir, f"{Z}.json")))
        z = {"title": zc["title"], "order": zc["order"], "offset": off, "ambience": zc.get("ambience"),
             "geometry": {"parts": {p["name"]: {k: v for k, v in p.items() if k in ("center", "kind", "color", "alpha", "selfillum")}
                                    for p in geo["parts"]},
                          "collision": [c["name"] for c in geo["collision"]],
                          "boxes": [{"cf": [b["cf"][0] + off[0], b["cf"][1] + off[1], b["cf"][2] + off[2]] + b["cf"][3:],
                                     "size": b["size"]} for b in geo["boxes"]],
                          "files": [f["file"] for f in geo["files"]]}}
        z["spawns"] = [zone_cf(o, off) for i, o, f in mbs("SpawnPoint") if "PlayerStartPoints" in o["path"]]
        for i, o, f in mbs("CameraLiteManager"):
            d = f.get("defaultCamera") or {}
            j = by_path.get(d.get("go"))
            if j is None:
                continue
            cam = next(c["fields"] for c in objs[j]["components"] if c.get("script", "").startswith("CameraLite"))
            z["camera"] = {"fov": cam.get("fieldOfView", 45)}
            for k in ("boomZoom", "boomForward", "boomIdle"):
                bm = cam.get(k)
                if bm:
                    v = np.array([bm["boom"][a] for a in "xyz"])
                    z["camera"][k] = {"dir": [round(float(x), 4) for x in P @ (v / max(np.linalg.norm(v), 1e-6))],
                                      "distance": round(bm["distance"] * K, 3), "enter": bm.get("minTimeToEnter", 1)}
        for i, o, f in mbs("AmbientOverride"):
            a = f["ambientColor"]
            z["ambient"] = [round(a["r"], 4), round(a["g"], 4), round(a["b"], 4)]
        z["fractals"] = [{"pos": pos(o["pos"], off), "flying": bool(f.get("onlyAccessibleToFlyingHeroes")),
                          "wallcrawl": bool(f.get("onlyAccessibleToWallCrawlHeroes"))} for i, o, f in mbs("FractalActivitySpawnPoint")]
        z["tokens"] = [{"pos": pos(o["pos"], off), "flying": bool(f.get("onlyAccessibleToFlyingHeroes")),
                        "wallcrawl": bool(f.get("onlyAccessibleToWallCrawlHeroes"))} for i, o, f in mbs("FeatherActivitySpawnPoint")]
        z["pigeons"] = [pos(o["pos"], off) for i, o, f in mbs("PigeonActivitySpawnPoint")]
        # civilian paths: follow nextNodes from each path's first node
        paths = []
        for i, o, f in mbs("NPCPath"):
            nodes = [k for k, x in enumerate(objs) if x["parent"] == i and any(c.get("script") == "NPCPathNode" for c in x["components"])]
            if not nodes:
                continue
            nf = {k: next(c["fields"] for c in objs[k]["components"] if c.get("script") == "NPCPathNode") for k in nodes}
            start = next((k for k in nodes if nf[k].get("startNode")), nodes[0])
            order, k = [], start
            while k is not None and k not in order:
                order.append(k)
                nx = [by_path.get(n.get("go")) for n in nf[k].get("nextNodes", []) if isinstance(n, dict)]
                k = next((n for n in nx if n in nf), None)
            paths.append([pos(objs[k]["pos"], off) for k in order])
        z["npcPaths"] = paths
        z["npcs"] = [{"pos": pos(o["pos"], off), "char": clean(f["CharacterName"])} for i, o, f in mbs("NPCSpawn")]
        z["launchers"] = []
        for i, o, f in mbs("UILauncherAdaptor"):
            rootname = objs[o["parent"]]["name"].lower() if o["parent"] >= 0 else ""
            kind = next((v for k, v in LAUNCHERS.items() if k in rootname), "zones")
            z["launchers"].append({"kind": kind, "pos": pos(objs[o["parent"]]["pos"], off), "type": f.get("LauncherType")})
        doors = []
        for i, o, f in mbs("DoorManager"):
            ex = (f.get("exit") or {}).get("go")
            j = by_path.get(ex)
            dock = next((k for k, x in enumerate(objs) if x["path"].startswith(o["path"] + "/") and
                         any(c.get("script") == "DockPoint" for c in x["components"])), i)
            doors.append({"name": clean(o["name"]), "cf": zone_cf(objs[dock], off), "exit": clean(objs[j]["name"]) if j is not None else None})
        z["doors"] = doors
        z["shops"] = [{"kind": s.replace("DoorManager", "").lower(), "pos": pos(o["pos"], off)}
                      for s in ("StoreDoorManager", "SnackDoorManager", "ArcadeDoorManager") for i, o, f in mbs(s)]
        z["musicZones"] = []
        for i, o, f in mbs("MusicZone"):
            src = (f.get("audioSrc") or {}).get("go", "").strip("/").replace("_audio", "")
            sz = f.get("size") or {"x": 0, "y": 0, "z": 0}
            z["musicZones"].append({"cf": zone_cf(o, off), "size": [round(sz["x"] * K, 2), round(sz["y"] * K, 2), round(sz["z"] * K, 2)],
                                    "music": clean(src)})
        z["emoteZones"] = [{"pos": pos(o["pos"], off), "emotes": (f.get("emoteList") or {}).get("emotes", [])} for i, o, f in mbs("EmoteZone")]
        z["signs"] = [{"text": s["text"], "cf": cf(s["center"], np.eye(3) if s["normal"] == [0, 0, 1] else np.eye(3)),
                       "size": [round(s["size"][0] * K, 3), round(s["size"][1] * K, 3)]} for s in zc.get("signs", [])]
        for s in z["signs"]:
            s["cf"][0] += off[0]
            s["cf"][1] += off[1]
            s["cf"][2] += off[2]
        pm = json.load(open(os.path.join(hub_dir, "props", f"{Z}_props.json")))
        merged = json.load(open(os.path.join(hub_dir, f"{Z}_Props.json")))
        for name, m in merged.items():  # prop boxes: Unity local matrices -> Roblox local CFrame + size
            boxes = []
            for b in m.get("boxes", []):
                M = np.array(b["matrix"])
                sc = np.linalg.norm(M[:3, :3], axis=0)
                ctr = M[:3, 3] + M[:3, :3] @ np.array(b["center"])
                boxes.append({"cf": cf(ctr, M[:3, :3] / np.where(sc == 0, 1, sc)),
                              "size": [round(float(x), 4) for x in np.array(b["size"]) * sc * K]})
            props[name] = {"parts": m["parts"], "collision": m["collision"], "boxes": boxes}
        z["props"] = [{"model": p["prop"], "cf": [p["cf"][0] + off[0], p["cf"][1] + off[1], p["cf"][2] + off[2]] + p["cf"][3:],
                       "scale": p["scale"], "kind": next((s for s in ("PokeAndJiggle", "ParkBenchController") if s in p["scripts"]),
                                                         "door" if any("Door" in s for s in p["scripts"]) else "static"),
                       "name": p["name"]} for p in pm["instances"] if p["prop"] in merged]
        zones[Z] = z
        print(f"{Z} ({zc['title']}): {len(z['geometry']['parts'])} parts, {len(z['geometry']['collision'])} collision chunks, "
              f"{len(z['props'])} props, {len(z['spawns'])} spawns, {len(z['fractals'])} fractals, {len(z['tokens'])} tokens, "
              f"{len(z['pigeons'])} pigeons, {len(paths)} paths, {len(z['npcs'])} npcs, {len(z['launchers'])} launchers, "
              f"{len(doors)} doors, {len(z['musicZones'])} music zones")
    body = "-- generated by tools/convert_hub.py from the original social zones: do not edit\nreturn " + \
        lua({"studsPerUnit": K, "Zones": zones, "Props": props, "Characters": CHARACTERS, "Civilians": CIVILIANS,
             "StartZone": "Bulletin"}) + "\n"
    check(body, "HubData.lua")
    open(os.path.join(root, "studio/game/shared/HubData.lua"), "w").write(body)
    print(f"wrote HubData.lua ({len(body) // 1024} KB)")


if __name__ == "__main__":
    main()
