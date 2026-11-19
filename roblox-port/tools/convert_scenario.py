"""Convert original missions (mission XML + scenario bundles exported by export_scenario.py) into
studio/game/shared/MissionData.lua: every stage's tile placements, scenario objects and event wiring in Roblox
space (studs, Roblox axes), for the Scenario runtime to run exactly like the game's ScenarioEventManager.

Unity -> Roblox: position (x, y, z) -> k (x, y, -z); rotation R -> P R P (P = diag(1, 1, -1)); k = 2.56.
Mirrored tile placements (negative scale) use the tile's mirrored model ("<Tile>_M", mirrored on local x).

Usage: python convert_scenario.py <roblox-port dir> <data_xml_dir> <strings.xml> <tile_dir> <scenario_json_dir>
           <mission_id> [<mission_id> ...]
"""
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spso_names import check, clean  # noqa: E402

K = 2.56
P = np.diag([1.0, 1.0, -1.0])

# display text: the licensed names become the port's names
TEXT_RULES = [(r"Super[- ]Skrull", "the Invader Warlord"), (r"Skrulls", "Invaders"), (r"Skrull", "Invader"),
              (r"Super Hero City", "Hero City"), (r"Super Hero Squad", "Hero Squad")]
# enemy roster: original character name -> port archetype (GameConfig.Enemies)
CHARACTERS = {"skrull_melee": "Thug", "skrull_rifle": "Blaster", "skrull_bazooka": "Bazooka", "skrull_grenade": "Grenadier",
              "super_skrull_boss": "Warlord", "skrull_popcorn": "Popcorn", "skrull_polymorph": "Shifter",
              "doombot_ranged": "BotGunner", "doombot_melee": "BotBrawler"}
# polymorph forms (the original copies licensed heroes): evil copies of the port's heroes
FORMS = {"captain_america": "Skyvolt", "captain_america_bucky": "Skyvolt", "thor": "Magmaul", "valkyrie": "Aurora",
         "cyclops": "Skyvolt", "emma_frost": "Aurora", "psylocke": "Aurora", "rogue": "Aurora", "wasp": "Aurora",
         "gambit": "NightGecko", "giant_man": "Magmaul", "she_hulk": "ElRugido", "she_hulk_red": "ElRugido",
         "hulk_gladiator": "ElRugido"}


def cap(s):
    return s[:1].upper() + s[1:]


def display(s):
    for a, b in TEXT_RULES:
        s = re.sub(a, b, s)
    s = re.sub(r"^the ", "The ", s)
    check(s, "display text")
    return s


def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def cf(pos, R):
    """Roblox CFrame components from a Unity world position and rotation matrix"""
    p = P @ np.array(pos) * K
    r = P @ R @ P
    return [round(float(v), 4) for v in p] + [round(float(v), 6) for v in r.reshape(-1)]


def obj_cf(o):
    return cf(o["pos"], quat_mat(o["rot"]))


def vec(v, scale=K, flip=True):
    return [round(v["x"] * scale, 4), round(v["y"] * scale, 4), round((-v["z"] if flip else v["z"]) * scale, 4)]


class Stage:
    def __init__(self, scen, strings, audio_refs, tiles_dir):
        self.d = scen
        self.objs = scen["objects"]
        self.strings = strings
        self.audio = audio_refs
        self.tiles_dir = tiles_dir
        self.kids = {}
        for i, o in enumerate(self.objs):
            self.kids.setdefault(o["parent"], []).append(i)
        self.by_path = {o["path"]: i for i, o in enumerate(self.objs)}
        self.ids = {}
        self.used_props = set()
        self.skip = set()
        for i, o in enumerate(self.objs):  # editor-only gizmos and the __DISABLED group
            if o["name"] == "__DISABLED" or any(c.get("script") == "DestroyOnLoad" for c in o["components"]):
                self.skip_tree(i)

    def subtree(self, i):
        out = [i]
        for k in self.kids.get(i, []):
            out += self.subtree(k)
        return out

    def skip_tree(self, i):
        self.skip.add(i)
        for k in self.kids.get(i, []):
            self.skip_tree(k)

    def mb(self, i, script):
        return [c for c in self.objs[i]["components"] if c.get("script") == script]

    def comp(self, i, t):
        return next((c for c in self.objs[i]["components"] if c["type"] == t), None)

    def text(self, key):
        if not key:
            return ""
        k = key.lstrip("#").upper()
        v = self.strings.get(k) or self.strings.get("MIS_" + k) or key
        return display(v)

    def box(self, i, c):
        """Roblox CFrame + size of a BoxCollider on object i"""
        o = self.objs[i]
        R = quat_mat(o["rot"])
        s = np.abs(np.array(o["scale"]))
        ctr = np.array([c["center"]["x"], c["center"]["y"], c["center"]["z"]]) * np.array(o["scale"])
        world = np.array(o["pos"]) + R @ ctr
        size = np.array([c["size"]["x"], c["size"]["y"], c["size"]["z"]]) * s * K
        return {"cf": cf(world, R), "size": [round(float(v), 4) for v in size]}

    def ref_index(self, ref):
        if isinstance(ref, dict) and "go" in ref:
            return self.by_path.get(ref["go"])
        return None

    def audio_key(self, ref):
        """ShsMissionMusic -> ShsAudioSource prefab at the bundle root -> tagged audio key -> sound name"""
        if not ref or "go" not in ref:
            return None
        name = ref["go"].strip("/").replace("_audio", "")
        src = self.d.get("audio_sources", {}).get(ref["go"].strip("/"))
        if src:
            for clip in src.get("Clips", []):
                if clip.get("AssetName"):
                    tagged = self.audio.get(clip["AssetName"].lower())
                    if tagged:
                        return clean(tagged)
                if isinstance(clip.get("Clip"), dict) and clip["Clip"].get("name"):
                    return clean(clip["Clip"]["name"])
        return clean(name)

    def tiles(self):
        out = []
        for t in self.d["tiles"]:
            W = quat_mat(t["rot"]) * np.array(t["scale"])
            mirror = np.linalg.det(W) < 0
            if mirror:
                W = W @ np.diag([-1.0, 1, 1])
            s = np.linalg.norm(W, axis=0)
            R = W / s
            name = cap(clean(t["prefab"])) + ("_M" if mirror else "")
            out.append({"tile": name, "base": name, "mirror": bool(mirror),
                        "cf": cf(t["pos"], R), "scale": round(float(s.mean()), 5)})
        return out

    def convert(self):
        st = {"spawns": [], "controllers": [], "sources": [], "triggers": [], "transfers": [], "disables": [],
              "objectives": [], "walls": [], "players": [], "waypoints": [], "crates": [], "objectSpawners": [],
              "periodic": [], "sfx": []}
        spawn_id = {}

        def spawn_entry(i, c):
            f = c["fields"]
            o = self.objs[i]
            char = f["CharacterName"]
            e = {"id": len(st["spawns"]) + 1, "char": clean(char), "archetype": CHARACTERS.get(char), "cf": obj_cf(o),
                 "players": [int(f.get(f"Players{n}", 1)) for n in range(1, 5)], "boss": bool(f.get("IsBoss")),
                 "aggro": round(f.get("aggroDistance", 0) * K, 3) if f.get("overrideAggroDistance") else None,
                 "wakeOnAggro": bool(f.get("wakeUpOnAggro", 1)), "wakeOnHit": bool(f.get("wakeUpOnHit", 1)),
                 "points": bool(f.get("rewardsPoints", 1)), "transport": bool(f.get("doTransportEffect", 1)),
                 "effect": clean(f.get("startingEffect") or "") or None, "r2": f.get("R2Attack"), "name": clean(o["name"])}
            src = self.ref_index(f.get("spawnInSource"))
            if src is not None:
                e["source"] = self.source_id(src, st)
            if c["script"] == "PolymorphSpawn":
                e["forms"] = [{"hero": FORMS.get(pf["characterName"], "ElRugido"), "r2": pf.get("r2Attack", 1),
                               "enemy": bool(pf.get("changeToEnemy")), "effect": clean(pf.get("startingEffect") or "") or None}
                              for pf in f.get("polymorphForms") or []]
            st["spawns"].append(e)
            spawn_id[i] = e["id"]
            return e["id"]

        self._sources = {}
        for i, o in enumerate(self.objs):
            if i in self.skip:
                continue
            for c in o["components"]:
                s = c.get("script")
                f = c.get("fields", {})
                if s in ("CharacterSpawn", "PolymorphSpawn"):
                    if f.get("IsPlayer"):
                        st["players"].append(obj_cf(o))
                    elif i not in spawn_id:
                        spawn_entry(i, c)
                elif s == "SpawnController":
                    ctl = {"oid": i, "name": clean(o["name"]), "enable": f["enableEvent"], "disable": f["disableEvent"],
                           "destruct": f.get("destructEvent", ""), "initial": f["initialSpawns"], "waveSize": f["spawnWaveSize"],
                           "waitFull": bool(f["waitForFullWave"]), "minActive": f["minimumActiveSpawns"],
                           "maxActive": f["maximumActiveSpawns"], "rate4": f["spawnRateMultiplier4Player"],
                           "total": f["totalSpawns"], "total4": f["totalSpawnMultiplier4Player"], "interval": f["spawnInterval"],
                           "batch": f["batchInterval"], "order": f.get("spawnOrder", 0), "complete": f["spawnCompleteEvent"],
                           "die": f["spawnDieEvent"], "wake": f["spawnWakeEvent"], "choices": []}
                    for k in self.kids.get(i, []):
                        if k in self.skip:
                            continue
                        cs = self.mb(k, "CharacterSpawn") + self.mb(k, "PolymorphSpawn")
                        grp = self.mb(k, "SpawnGroup")
                        if cs:
                            ctl["choices"].append({"spawn": spawn_id.get(k) or spawn_entry(k, cs[0])})
                        elif grp:
                            members = []
                            for g in self.kids.get(k, []):
                                gcs = self.mb(g, "CharacterSpawn") + self.mb(g, "PolymorphSpawn")
                                if gcs and g not in self.skip:
                                    members.append(spawn_id.get(g) or spawn_entry(g, gcs[0]))
                            ctl["choices"].append({"group": members, "order": grp[0]["fields"].get("spawnOrder", 0)})
                    st["controllers"].append(ctl)
                elif s == "ColliderPopulationTrigger":
                    bc = self.comp(i, "BoxCollider")
                    if bc is None:
                        continue
                    b = self.box(i, bc)
                    if not bc.get("trigger"):
                        st["walls"].append({**b, "name": clean(o["name"])})
                    if f.get("TriggerScenarioEvent"):
                        st["triggers"].append({**b, "oid": i, "event": f["TriggerScenarioEvent"], "playerOnly": bool(f.get("PlayerOnly")),
                                               "enemyOnly": bool(f.get("EnemyOnly")), "oneShot": bool(f.get("OneShot")),
                                               "goal": f.get("PopulationGoal", 1), "onMet": bool(f.get("FireOnGoalMet", 1)),
                                               "onLost": bool(f.get("FireOnGoalLost")), "reset": f.get("TriggerResetTime", 0),
                                               "delay": f.get("TriggerFiringDelay", 0), "name": clean(o["name"])})
                elif s == "ScenarioEventTransferBox":
                    st["transfers"].append({"oid": i, "enable": f.get("enableEvent", ""), "disable": f.get("disableEvent", ""),
                                            "events": [e for e in f.get("triggeringEvents") or [] if e],
                                            "eventsMP": [e for e in f.get("triggeringEventsMultiplayer") or [] if e],
                                            "send": f.get("sendEvent", ""), "delay": f.get("timeDelay", 0),
                                            "repeatable": bool(f.get("repeatable"))})
                elif s == "DisableObjectScenarioEvent":
                    if f.get("enableEvent"):
                        st["disables"].append({"enable": f["enableEvent"], "disable": f.get("disableEvent", ""),
                                               "object": clean(o["path"].split("ScenarioObjects/")[-1]),
                                               "targets": self.subtree(i)})
                elif s == "NewObjectiveScenarioEvent":
                    st["objectives"].append({"enable": f["enableEvent"], "text": self.text(f.get("newObjectiveText", ""))})
                elif s == "IndicatorWaypoint":
                    dis = next((x["fields"]["enableEvent"] for x in self.mb(i, "DisableObjectScenarioEvent")), "")
                    st["waypoints"].append({"oid": i, "cf": obj_cf(o), "icon": f.get("indicatorIcon"), "hideOn": dis,
                                            "object": clean(o["path"].split("ScenarioObjects/")[-1])})
                elif s == "ObjectCombatController" and "pickup_spawner" in o["name"]:
                    bc = self.comp(i, "BoxCollider")
                    st["crates"].append({"cf": obj_cf(o), "box": self.box(i, bc) if bc else None, "drops": f.get("dropTableName"),
                                         "event": f.get("destructionScenarioEvent") or None})
                elif s == "ObjectSpawnRegion":
                    bc = self.comp(i, "BoxCollider")
                    prefab = (f.get("objectPrefab") or {}).get("go", "").strip("/")
                    st["objectSpawners"].append({"oid": i, "enable": f["enableEvent"], "disable": f.get("disableEvent", ""),
                                                 "start": bool(f.get("startEnabled")), "prefab": clean(prefab),
                                                 "frequency": f.get("frequency"), "batch": f.get("batchSize"),
                                                 "quantity": f.get("quantity"), "maxAlive": f.get("maximumSimultaneous"),
                                                 "reset": bool(f.get("resetQuantityOnEnable")), "ground": bool(f.get("snapToGround")),
                                                 "height": (f.get("spawnHeight") or 0) * K, "velocity": vec(f.get("velocity") or {"x": 0, "y": 0, "z": 0}),
                                                 "region": self.box(i, bc) if bc else {"cf": obj_cf(o), "size": [0, 0, 0]},
                                                 "diorama": "Diorama" in o["path"]})
                elif s == "ScenarioEventPeriodicEvent":
                    st["periodic"].append({"oid": i, "enable": f.get("enableEvent", ""), "disable": f.get("disableEvent", ""),
                                           "event": f["periodicEvent"], "period": f.get("period"), "startPeriod": bool(f.get("startPeriod"))})
                elif s == "ShsMissionMusic":
                    st["music"] = {"level": self.audio_key(f.get("levelMusic")), "boss": self.audio_key(f.get("bossMusic")),
                                   "complete": self.audio_key(f.get("missionCompleteMusic")),
                                   "bossEvent": f.get("bossMusicStartEvent", ""), "levelEvent": f.get("levelMusicStartEvent", ""),
                                   "onlyOnEvent": bool(f.get("onlyStartLevelMusicOnEvent")), "fade": f.get("fadeTime", 1)}
                elif s == "CameraLiteSpring" and "___CAMERA" in o["path"]:
                    t2c = np.array([f["targetToCamera"][a] for a in "xyz"])
                    d = f.get("distanceFromTarget") or float(np.linalg.norm(t2c))
                    off = P @ (t2c / np.linalg.norm(t2c) * d) * K
                    st["camera"] = {"offset": [round(float(v), 4) for v in off], "rot": cf([0, 0, 0], quat_mat(o["rot"]))[3:],
                                    "fov": f.get("fieldOfView", 45), "spring": f.get("springEnabled", 1) == 1,
                                    "k": f.get("springConstant", 100), "damping": f.get("springDamping", 15),
                                    "mass": f.get("springMass", 1)}
                elif s == "AmbientOverride":
                    a = f["ambientColor"]
                    st["ambient"] = [round(a["r"], 4), round(a["g"], 4), round(a["b"], 4)]
            # solid scenario walls (invisible walls, blockers); trigger boxes handled above
            if not any(c.get("script") in ("ColliderPopulationTrigger", "ObjectCombatController", "ObjectSpawnRegion")
                       for c in o["components"]):
                bc = self.comp(i, "BoxCollider")
                if bc is not None and not bc.get("trigger") and bc.get("enabled", True) and "Diorama" not in o["path"]:
                    st["walls"].append({**self.box(i, bc), "name": clean(o["name"])})
        st["sources"] = [v for _, v in sorted(self._sources.items(), key=lambda kv: kv[1]["id"])]
        st["props"] = self.props()
        st["lasers"] = self.lasers()
        return st

    def props(self):
        """static scenario props that have an exported model (port_tile.py output) - not the moving spline ships"""
        out = []
        for i, o in enumerate(self.objs):
            if i in self.skip or any(k in o["path"] for k in ("/Splines/", "/skrull_ship/", "Satellite_Splines", "/Diorama/", "/TileReferences/")):
                continue
            name = cap(clean(o["name"]))
            pj = os.path.join(self.tiles_dir, f"{name}.json")
            if not os.path.exists(pj) or not json.load(open(pj))["parts"]:
                continue
            W = quat_mat(o["rot"]) * np.array(o["scale"])
            mirror = np.linalg.det(W) < 0
            if mirror:
                W = W @ np.diag([-1.0, 1, 1])
            sc = np.linalg.norm(W, axis=0)
            crate = "pickup_spawner" in o["path"]
            out.append({"model": name + ("_M" if mirror else ""), "mirror": bool(mirror), "cf": cf(o["pos"], W / sc),
                        "scale": round(float(sc.mean()), 5), "crate": crate})
            self.used_props.add(name + ("_M" if mirror else ""))
        return out

    def lasers(self):
        """laser gate quads (gate objects): world corners -> centre, length axis, width"""
        out = []
        for i, o in enumerate(self.objs):
            if i in self.skip or not o["name"].startswith("gate0") or not self.mb(i, "DisableObjectScenarioEvent"):
                continue
            for k in self.kids.get(i, []):
                ko = self.objs[k]
                if self.comp(k, "MeshFilter") is None:
                    continue
                W = quat_mat(ko["rot"]) * np.array(ko["scale"])
                # the gate quad (Plane01): local XY, -0.2..0.2
                ax = [W[:, 0] * 0.4, W[:, 1] * 0.4]
                L = [np.linalg.norm(a) for a in ax]
                long_i = int(np.argmax(L))
                d = ax[long_i] / L[long_i]
                out.append({"cf": cf(ko["pos"], quat_mat(ko["rot"])), "length": round(float(L[long_i] * K), 3),
                            "width": round(float(L[1 - long_i] * K), 3), "dir": [round(float(x), 4) for x in P @ d]})
        return out

    def source_id(self, i, st):
        if i not in self._sources:
            o = self.objs[i]
            f = self.mb(i, "BrawlerSpawnSource")[0]["fields"]
            self._sources[i] = {"id": len(self._sources) + 1, "cf": obj_cf(o), "anim": f.get("spawnAnimation"),
                                "animSpeed": f.get("spawnAnimationSpeed", 1), "speed": f.get("spawnInSpeed", 10) * K,
                                "startAngle": f.get("startAngle", 0), "endAngle": f.get("endAngle", 0),
                                "freeFall": bool(f.get("freeFallOnCompletion", 1)), "fullAnim": bool(f.get("playFullAnimation"))}
        return self._sources[i]["id"]


EVENT_KEYS = {"enable", "disable", "destruct", "complete", "die", "wake", "event", "send", "events", "eventsMP",
              "bossEvent", "levelEvent", "hideOn"}


def clean_events(v, key=None):
    """event names ship in scripts too: clean them all the same way so the wiring stays intact"""
    if isinstance(v, dict):
        return {k: clean_events(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [clean_events(x, key) for x in v]
    if isinstance(v, str) and key in EVENT_KEYS:
        return clean(v)
    return v


def lua(v, ind=0):
    pad = "\t" * ind
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        f = float(v)
        if math.isinf(f) or math.isnan(f):
            return "0"
        return repr(round(f, 6))
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        if all(isinstance(x, (int, float, np.number)) and not isinstance(x, bool) for x in v):
            return "{" + ", ".join(lua(x) for x in v) + "}"
        return "{\n" + "".join(f"{pad}\t{lua(x, ind + 1)},\n" for x in v) + pad + "}"
    if isinstance(v, dict):
        items = []
        for k, x in v.items():
            key = k if re.match(r"^[A-Za-z_]\w*$", str(k)) else f"[{json.dumps(str(k))}]"
            items.append(f"{pad}\t{key} = {lua(x, ind + 1)},\n")
        return "{\n" + "".join(items) + pad + "}"
    raise TypeError(type(v))


def tile_data(tiles_dir, names):
    out = {}
    for n in sorted(names):
        p = os.path.join(tiles_dir, f"{n}.json")
        if not os.path.exists(p):
            print("missing tile export", n)
            continue
        d = json.load(open(p))
        out[n] = {"parts": {pt["name"]: {"center": pt["center"], "kind": pt["kind"],
                                          **({"color": pt["color"]} if "color" in pt else {}),
                                          **({"alpha": True} if pt.get("alpha") else {})} for pt in d["parts"]},
                  "collision": d["collision"],
                  "boxes": [{"cf": cf(np.array(b["matrix"])[:3, 3] + np.array(b["matrix"])[:3, :3] @ np.array(b["center"]),
                                       np.array(b["matrix"])[:3, :3] / np.linalg.norm(np.array(b["matrix"])[:3, :3], axis=0)),
                             "size": [round(float(x), 4) for x in np.array(b["size"]) * np.linalg.norm(np.array(b["matrix"])[:3, :3], axis=0) * K]}
                            for b in d.get("boxes", [])]}
    return out


def main():
    root, data_dir, strings_xml, tiles_dir, scen_dir = sys.argv[1:6]
    mission_ids = sys.argv[6:]
    strings = {k.lstrip("#").upper(): v for k, v in re.findall(r'<string id="([^"]+)">\s*<value><!\[CDATA\[(.*?)\]\]></value>',
                                                                 open(strings_xml, encoding="utf-8").read(), re.S)}
    audio = {}
    for ref in ET.parse(os.path.join(data_dir, "tagged_audio_references.xml")).getroot().iter("audio-reference"):
        audio[ref.findtext("key").lower()] = ref.findtext("asset")
    missions, all_tiles = {}, set()
    for mid in mission_ids:
        x = ET.parse(os.path.join(data_dir, f"{mid}.xml")).getroot()
        m = {"id": clean(mid), "name": display(x.findtext("name")), "description": display(x.findtext("description") or ""),
             "stages": [], "medals": {}}
        for medal in ("bronze", "silver", "gold", "adamantium"):
            e = x.find(f"rating/{medal}/score_needed")
            if e is not None:
                m["medals"][medal] = [int(p.text) for p in e.findall("player")]
        for stx in x.findall("stages/stage"):
            sid = stx.findtext("scenario_bundle")
            scen = json.load(open(os.path.join(scen_dir, f"{sid}.json")))
            stage = Stage(scen, strings, audio, tiles_dir)
            st = stage.convert()
            n = int(stx.findtext("stage_number"))
            st.update({"id": cap(clean(sid).replace("_scenario", "")), "number": n, "tiles": stage.tiles(),
                       "orders": stage.text(f"#{mid}_S{n}_ORDERS")})
            for t in st["tiles"]:
                all_tiles.add(t["tile"])
                t.pop("base")
            all_tiles |= stage.used_props
            m["stages"].append(st)
        missions[clean(mid)] = m
        print(f"{mid}: {m['name']} - " + ", ".join(f"{s['id']} ({len(s['tiles'])} tiles, {len(s['controllers'])} controllers, "
                                                    f"{len(s['spawns'])} spawns, {len(s['triggers'])} triggers)" for s in m["stages"]))
    missions = clean_events(missions)
    tiles = tile_data(tiles_dir, all_tiles)
    body = ("-- generated by tools/convert_scenario.py from the original mission data: do not edit\n"
            "return " + lua({"studsPerUnit": K, "Missions": missions, "Tiles": tiles}) + "\n")
    check(body, "MissionData.lua")
    json.dump({"Missions": missions, "Tiles": tiles}, open(os.path.join(scen_dir, "MissionData.json"), "w"))
    out = os.path.join(root, "studio/game/shared/MissionData.lua")
    open(out, "w").write(body)
    print(f"wrote {out} ({len(body) // 1024} KB), tiles: {sorted(tiles)}")


if __name__ == "__main__":
    main()
