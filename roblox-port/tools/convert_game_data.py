"""Convert the original game's data (the XML TextAssets inside Assets/Data-general.asset, extracted to a
folder) into studio/game/shared/GameData.lua for the Roblox port.

What it carries over, in studs (k studs per original unit) and seconds:
  * heroes: health, power, motion (speed, gravity, jump velocity, rotate speed), body capsule, attack
    colliders (bone + offset + scale), power multipliers, recoil/pushback/launch resistance
  * every attack of the L chain (L1-L5), the three power attacks (R1-R3, with their power cost) and the
    super: range, movement, chain window, effect sequence, and each impact (melee collider, projectile,
    beam, target): damage, recoil type, pushback, launch, knockdown, projectile speed/lifespan/gravity,
    explosion radius, hit limits, impact effect
  * whether each clip has its own collision/projectile AnimationEvents (from the hero packs)
  * enemy archetypes (from the original enemy files, mapped onto the port's models) and the brawler
    scoring rules (KO values, combo heat, survival bonus, medal ratios)
Every name passes through spso_names.clean() and the output is checked for branded names.

Usage: python convert_game_data.py <data_xml_dir> <roblox-port dir>
"""
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spso_names import check, clean  # noqa: E402

K = 2.56
HEROES = [  # port hero, original data file, display name
    ("ElRugido", "hulk", "El Rugido"), ("Skyvolt", "falcon", "Skyvolt"), ("Aurora", "ms_marvel", "Aurora"),
    ("Magmaul", "thing", "Magmaul"), ("NightGecko", "spider_man", "Night Gecko"),
]
SLOTS = {"attack_L1": "L1", "attack_L2": "L2", "attack_L3": "L3", "attack_L4": "L4", "attack_L5": "L5",
         "attack_R1": "R1", "attack_R2": "R2", "attack_R3": "R3", "attack_super": "Super"}
ENEMIES = {  # archetype -> original enemy file and the port model of its character bundle (original rig + clips)
    "Thug": {"xml": "skrull_melee", "model": "InvaderMelee", "displayName": "Invader Brawler"},
    "Blaster": {"xml": "skrull_rifle", "model": "InvaderGunner", "displayName": "Invader Gunner"},
    "Bazooka": {"xml": "skrull_bazooka", "model": "InvaderGunner", "displayName": "Invader Bazooka"},
    "Grenadier": {"xml": "skrull_grenade", "model": "InvaderGrenadier", "displayName": "Invader Grenadier"},
    "Warlord": {"xml": "super_skrull_boss", "model": "InvaderWarlord", "displayName": "Invader Warlord"},
    "Popcorn": {"xml": "skrull_popcorn", "model": "InvaderPopcorn", "displayName": "Invader Minion"},
    "Shifter": {"xml": "skrull_polymorph", "model": "InvaderMelee", "displayName": "Invader Shapeshifter"},
}
RANKS = ["fodder", "regular", "lieutenant", "miniboss", "boss", "megaboss"]


def num(e, tag, d=0.0):
    t = e.findtext(tag) if e is not None else None
    try:
        return float(t.strip()) if t and t.strip() else d
    except ValueError:
        return d


def flag(e, tag):
    return (e.findtext(tag) or "").strip().lower() == "true"


def r4(x):
    return round(float(x), 4)


def vec(e, tag, scale=1.0, flipz=True):
    v = e.find(tag) if e is not None else None
    if v is None:
        return [0, 0, 0]
    x, y, z = num(v, "x"), num(v, "y"), num(v, "z")
    return [r4(x * scale), r4(y * scale), r4((-z if flipz else z) * scale)]


def stats(root):
    out = {}
    for s in root.find("character_stats") or []:
        out[(s.findtext("stat_type") or "").strip()] = num(s, "initial_maximum", num(s, "initial_value"))
    return out


def projectile_kind(name):
    n = (name or "").lower()
    if "web" in n:
        return "web"
    if "feather" in n or "shard" in n:
        return "shard"
    if "rifle" in n or "bullet" in n or "projectile" in n:
        return "bolt"
    return "orb"


def colliders(root):
    out = {}
    for c in root.findall("character_model/collider"):
        out[clean(c.findtext("name") or "")] = {"node": (c.findtext("node") or "").strip(),
                                                "offset": vec(c, "offset", K), "scale": r4(num(c, "scale", 1))}
    return out


def impact(i, cols):
    t = int(num(i, "impact_type"))
    col = clean((i.findtext("collider") or "").strip())
    base = cols.get(col, {}).get("scale", 1.0)
    out = {"type": t, "collider": col, "damage": r4(num(i, "damage")), "recoil": int(num(i, "recoil")),
           "pushback": r4(num(i, "pushback_velocity") * K), "pushTime": r4(num(i, "pushback_duration")),
           "launch": r4(num(i, "launch_velocity") * K), "knockTime": r4(num(i, "knockdown_duration")),
           "recoilTime": r4(num(i, "recoil_duration")),
           "radius": r4(0.5 * K * base * num(i, "collider_scale", 1)), "maxTargets": int(num(i, "maximum_targets_hit", 1)),
           "maxHits": int(num(i, "maximum_hits_per_target", 1)), "angle": r4(num(i, "collider_angle_limit", 180)),
           "start": r4(num(i, "impact_start_time")), "stop": r4(num(i, "impact_end_time")), "fire": r4(num(i, "firing_time")),
           "fromCollider": flag(i, "pushback_from_collider"), "hitsFriends": flag(i, "hits_friends")}
    eff = clean((i.findtext("impact_effect") or "").strip())
    if eff:
        out["effect"] = eff
    ev = clean((i.findtext("event_name") or "").strip())  # scenario event fired by the hit (boss flames...)
    if ev:
        out["event"] = ev
    ace = clean((i.findtext("attacker_combat_effect") or "").strip())
    if ace:
        out["attackerEffect"] = ace
    if t == 1:
        out.update({"speed": r4(num(i, "projectile_speed") * K), "life": r4(num(i, "projectile_lifespan", 3)),
                    "gravity": r4(num(i, "projectile_gravity") * K), "explode": r4(num(i, "projectile_explosion_radius") * K),
                    "aimed": flag(i, "projectile_aimed"), "ballistic": flag(i, "projectile_ballistic"),
                    "destroyOnImpact": flag(i, "projectile_destroy_on_impact") or not i.findtext("projectile_destroy_on_impact"),
                    "visual": projectile_kind(i.findtext("projectile_name"))})
    return out


def attacks(root, cols, events):
    out = {}
    for a in root.findall("attack_data/attack"):
        anim = (a.findtext("anim") or "").strip()
        key = SLOTS.get(anim, anim)
        if key in out:
            continue  # tiers 2/3 of the same move (upgrades) come later in the list
        ev = events.get(anim, {})
        att = {"anim": anim, "cost": r4(num(a, "power_cost")), "range": r4(num(a, "maximum_range") * K),
               "desired": r4(num(a, "desired_range") * K), "moveSpeed": r4(num(a, "move_speed") * K),
               "forward": r4(num(a, "forward_speed") * K), "faceTarget": flag(a, "face_target"),
               "trackTarget": flag(a, "track_target"), "targetless": flag(a, "targetless_attack"),
               "chainStart": r4(num(a, "chain_start_time")), "chainEnd": r4(num(a, "chain_end_time")),
               "collisionOn": r4(num(a, "collision_on_time", -1)), "collisionOff": r4(num(a, "collision_off_time", -1)),
               "events": {"collision": ev.get("OnCollisionEnableAnimTag", 0), "projectile": ev.get("OnProjectileFireAnimTag", 0)},
               "impacts": [impact(i, cols) for i in a.findall("impact")]}
        eff = clean((a.findtext("effect") or "").strip())
        if eff and eff.lower() != "none":
            att["effect"] = eff
        out[key] = att
    return out


def clip_events(port_dir, hero):
    p = os.path.join(port_dir, "heroes", hero, "runtime", f"{hero}.pack.json")
    if not os.path.exists(p):
        return {}, {}
    pj = json.load(open(p))
    ev = {}
    for c in pj["clips"]:
        d = ev.setdefault(c["name"], {})
        for e in c.get("events", []):
            fn = e.get("function") or e.get("fn") or ""
            d[fn] = d.get(fn, 0) + 1
    return ev, {c["name"]: r4(c["duration"]) for c in pj["clips"]}


def character(root, events):
    st = stats(root)
    mc = root.find("character_motion_controller")
    cc = root.find("character_controller")
    pcc = root.find("player_combat_controller")
    comb = root.find("player_combat_controller/combat_controller") or root.find("combat_controller")
    cols = colliders(root)
    return {
        "health": st.get("Health", 100), "power": st.get("Power", 0),
        "speed": r4(num(mc, "speed", 6) * K), "runAnimSpeed": r4(num(mc, "run_animation_speed", 1)),
        "gravity": r4(num(mc, "gravity", 20) * K), "jump": r4(num(mc, "jump_height", 10) * K),
        "terminal": r4(20 * K), "rotateSpeed": r4(num(mc, "rotate_speed", 500)),
        "height": r4(num(cc, "height", 2) * K), "radius": r4(num(cc, "radius", 0.5) * K),
        "centerY": r4(num(cc.find("center") if cc is not None else None, "y", 1) * K),
        "powerDealt": r4(num(pcc, "power_damage_dealt_multiplier", 0.5)),
        "powerReceived": r4(num(pcc, "power_damage_received_multiplier", 0.5)),
        "recoilResist": int(num(comb, "recoil_resistance")), "pushbackResist": r4(num(comb, "pushback_resistance")),
        "launchResist": r4(num(comb, "launch_resistance")), "recoilLimit": int(num(comb, "recoil_limit")),
        "rank": int(num(root, "scoring/defeat", 1)),
        "colliders": cols, "attacks": attacks(root, cols, events),
    }


def to_lua(v, ind=""):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return "0"
        return repr(int(v)) if float(v).is_integer() else repr(round(v, 4))
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "{" + ", ".join(to_lua(x, ind) for x in v) + "}"
    if isinstance(v, dict):
        if not v:
            return "{}"
        inner = ind + "\t"
        items = []
        for k in sorted(v, key=str):
            key = k if isinstance(k, str) and k.isidentifier() else f"[{json.dumps(k)}]"
            items.append(f"{inner}{key} = {to_lua(v[k], inner)},")
        return "{\n" + "\n".join(items) + "\n" + ind + "}"
    raise TypeError(type(v))


def main():
    data_dir, port_dir = sys.argv[1:3]
    load = lambda n: ET.parse(os.path.join(data_dir, n + ".xml")).getroot()  # noqa: E731
    out = {"studsPerUnit": K, "Heroes": {}, "Enemies": {}, "HeroOrder": [h for h, _, _ in HEROES]}
    durations = {}
    for hero, src, display in HEROES:
        ev, durations[hero] = clip_events(port_dir, hero)
        h = character(load(src), ev)
        h["displayName"] = display
        for a in h["attacks"].values():
            a["duration"] = durations[hero].get(a["anim"], 0)
        out["Heroes"][hero] = h
    for name, spec in ENEMIES.items():
        model = spec["model"]
        ev, durations[model] = clip_events(port_dir, model)
        e = character(load(spec["xml"]), ev)
        for a in e["attacks"].values():
            a["duration"] = durations[model].get(a["anim"], 0)
        missing = [k for k, a in e["attacks"].items() if a["anim"] not in durations[model]]
        for k in missing:  # moves whose clip the bundle does not have
            del e["attacks"][k]
        e.update({"displayName": spec["displayName"], "model": model})
        out["Enemies"][name] = e
    out["Models"] = [h for h, _, _ in HEROES] + sorted({s_["model"] for s_ in ENEMIES.values()})
    sc = load("brawler_scoring")
    out["Scoring"] = {
        "koValues": [int(num(sc, f"enemy_bonus/{r}")) for r in RANKS],
        "survivalBonus": [num(sc, f"defeated_bonus/deaths_{i}") for i in range(4)],
        "medalRatios": {"adamantium": num(sc, "score_calculator/adamantium_ratio"), "gold": num(sc, "score_calculator/gold_ratio"),
                        "silver": num(sc, "score_calculator/silver_ratio")},
        "comboWaveLoss": num(sc, "score_calculator/combo_wave_loss"), "comboSpawnerLoss": num(sc, "score_calculator/combo_spawner_loss"),
        "pickupBonus": num(sc, "pickup_bonus"),
        # BrawlerStatManager constants
        "comboGainPerDamage": 0.025, "comboLossPerDamage": 0.0125, "comboLossRate": 0.05, "comboMax": 3,
    }
    lua = ("-- GENERATED by tools/convert_game_data.py from the original game data. Do not edit by hand:\n"
           "-- change the converter (or GameConfig for port tuning) and run it again.\n"
           "return " + to_lua(out) + "\n")
    check(lua, "GameData.lua")
    path = os.path.join(port_dir, "studio", "game", "shared", "GameData.lua")
    open(path, "w").write(lua)
    for hero, h in out["Heroes"].items():
        missing = sorted({i["collider"] for a in h["attacks"].values() for i in a["impacts"]} - set(h["colliders"]))
        print(f"{hero:11s} hp {h['health']:.0f} speed {h['speed']} attacks {sorted(h['attacks'])}" +
              (f" | colliders not on the model: {missing}" if missing else ""))
    print("enemies:", {k: (v["health"], sorted(v["attacks"])) for k, v in out["Enemies"].items()})
    print(f"wrote {path} ({len(lua) / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
