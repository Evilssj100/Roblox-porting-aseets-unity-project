"""The original in-game store -> studio/game/shared/StoreData.lua.

Source: the revival server's catalog (shso-server rasp/data/json/shopping_catalog.json: catalog_ownable_id, category,
gold price, fractal price, visibility, priority), its ownables list, the potions (expendables.xml: effect handlers
and parameters) and the English strings (en-us_strings.xml) for names and descriptions.

Kept as in the original: the left-nav categories and their order, prices in gold and fractals, generic potions,
titles, fractal bags, the badge / medallion price tiers, generic sidekicks (listed, not sold yet: no models). The licensed catalog (heroes, their badges, medallions,
quests, missions, mystery boxes, bundles, crafts, booster packs) becomes the port's own content where it exists
(its heroes, their badges and medallions) and "coming soon" categories otherwise. Titles and sidekicks that
allude to licensed characters are left out (TITLE_DENY, SIDEKICK_ALLOW), and three potion descriptions that named
licensed characters are rewritten (DESC_OVERRIDE).

Usage: python convert_store.py <roblox-port dir> <catalog.json> <ownables.json> <expendables.xml> <en-us_strings.xml>
"""
import json
import os
import re
import statistics
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_scenario import lua  # noqa: E402
from spso_names import BANNED, check  # noqa: E402

# the original left nav (ShoppingWindowLeftPanel), its label colours; "soon": licensed content still to replace
NAV = [("new", "New!", (255, 209, 81)), ("heroes", "Heroes", (238, 29, 29)), ("badges", "Badges", None),
       ("crafts", "Crafts", None), ("missions", "Missions", None), ("mystery", "Mystery Boxes", None),
       ("potions", "Potions", None), ("cards", "Cards", None), ("sidekicks", "Sidekicks", None),
       ("titles", "Titles", None), ("gear", "Gear", None), ("misc", "Misc", None), ("medallions", "Medallions", None),
       ("bundles", "Bundles", None)]
SOON = {"crafts", "missions", "mystery", "cards", "gear", "bundles"}
HEROES = {"ElRugido": "A masked powerhouse who wrestles trouble into submission.",
          "Skyvolt": "A high-flyer who rides the wind and strikes like lightning.",
          "Aurora": "A radiant flyer who blasts villains with starlight.",
          "Magmaul": "A living volcano with fists of molten rock.",
          "NightGecko": "A wall-crawling acrobat who strikes from the shadows."}
# potions the port runs now (the rest of the original potions are listed as coming soon)
POTION_EFFECTS = {
    266658: {"type": "material", "material": "Foil", "color": [0.93, 0.74, 0.22]},           # Gold Potion
    266659: {"type": "material", "material": "Glass", "color": [0.82, 0.9, 1.0], "transparency": 0.55},  # Ghost
    266660: {"type": "fade", "transparency": 0.85},                                           # Invisibility
    275826: {"type": "tint", "color": [0.288, 0.953, 0.288]},                                 # St Patrick's
    291735: {"type": "tint", "color": [0.0, 0.0, 0.0]},                                       # Void
    291736: {"type": "tint", "color": [0.0, 0.0, 0.0], "transparency": 0.5},                  # Shadow
}
POTION_EXCLUDE = {291734}  # its mask is a licensed character's
POTION_ICONS = {"goody_effects_gold_shopping": "potion_gold", "goody_effects_astral_shopping": "potion_ghost",
                "goody_effects_invisible_shopping": "potion_invisible"}
# descriptions that named a licensed character, rewritten in the port's own words
DESC_OVERRIDE = {265424: "Grow to giant size with this specially formulated potion.",
                 643112: "A bubbling formula that gives one of your heroes 1000 XP!",
                 643114: "An improved bubbling formula that gives one of your heroes 5000 XP!"}
# sidekicks kept: generic animals and monsters (the rest are licensed characters, their minis or parodies)
SIDEKICK_ALLOW = {"Alley Cat", "Junkyard Dog", "Fire Imp", "Frost Imp", "Astral Imp", "Dragonfly", "Eyebot", "Vampire Bat",
                  "Zombie Guy", "Zombie Gal", "Mini Mummy", "Green Lizardling", "Striped Lizardling", "Red Lizardling",
                  "Pigeon", "Bunny", "Bunny King", "Mini Sasquatch", "Mini Frankenstein", "Mini Werewolf",
                  "Arcane Pigeon", "Frankenpigeon"}
TITLE_DENY = {"Bunnishing", "Ant-Sized", "Arachnid", "Webbed", "Uncanny", "True Believing", "Astonishing", "Invisible", "Superior",
              "Ultimate", "Wonderful", "Beastly", "Strange", "Scarlet", "Visionary", "Venomous", "Next Big Thing",
              "Inhuman", "Mutant", "Patriotic", "All-American", "Star-Spangled", "Super-Soldier", "Marvelous",
              "Fantastic", "Deadpooligan", "Hulkbusting", "Stark-Powered", "Squirrel-Powered", "Destroyer of Worlds"}


def main():
    root, cat_p, own_p, exp_p, str_p = sys.argv[1:6]
    S = {s.get("id"): (s.findtext("value") or "") for s in ET.parse(str_p).getroot().findall("string")}
    cat = [i for b in json.load(open(cat_p))["shopping-catalog"] for i in b["items"]]
    own = json.load(open(own_p))["ownableslist"]
    exp = {}
    for e in ET.parse(exp_p).getroot().findall("expendable"):
        exp[(e.findtext("id") or "").strip()] = (e.findtext("shopping_icon") or "").strip()
    def text(k):
        return (S.get(k, k) or "").strip()

    items, by_nav = {}, {n: [] for n, _, _ in NAV}

    def add(iid, nav, **kw):
        kw.setdefault("qty", 1)
        items[iid] = {"id": iid, "nav": nav, **kw}
        by_nav[nav].append(iid)

    tiers = {}
    for i in cat:
        tiers.setdefault(i["category"], []).append((i["price"], i["shard_price"]))

    def tier(c, k=0):
        return int(statistics.median(p[k] for p in tiers[c]))
    # heroes: the port's own (all five are starter heroes for now: owned by everyone)
    hero_gold, hero_fr = 240, 2400
    for h, desc in HEROES.items():
        add(f"hero_{h}", "heroes", kind="hero", hero=h, name=None, desc=desc, gold=hero_gold, fractals=hero_fr,
            icon=f"hero_{h}", starter=True, priority=10)
    # badges (silver unlocks more hero levels, gold all of them: original tiers)
    badge_names = {o["id"]: o["name"] for o in own if o["cat"] == "badge"}
    silver = [(i["price"], i["shard_price"]) for i in cat if i["category"] == "badge" and not badge_names.get(i["ownable_type_id"], "").endswith("_2")]
    gold = [(i["price"], i["shard_price"]) for i in cat if i["category"] == "badge" and badge_names.get(i["ownable_type_id"], "").endswith("_2")]
    sg, sf = int(statistics.median(p[0] for p in silver)), int(statistics.median(p[1] for p in silver))
    gg, gf = (int(statistics.median(p[0] for p in gold)), int(statistics.median(p[1] for p in gold))) if gold else (sg * 3, sf * 3)
    for h in HEROES:
        add(f"badge1_{h}", "badges", kind="badge", hero=h, level=1, gold=sg, fractals=sf, icon="shop_badge_silver",
            desc="Purchase this Badge to unlock more levels and more powerful attacks!", priority=5)
        add(f"badge2_{h}", "badges", kind="badge", hero=h, level=2, gold=gg, fractals=gf, icon="shop_badge_gold",
            desc="Purchase this Badge to unlock every level and the most powerful attacks!", priority=4, requires=f"badge1_{h}")
    # medallions: "Favorite Hero" for the port's heroes (the original's other medallions are licensed symbols)
    mg, mf = tier("mdln", 0), tier("mdln", 1)
    for h in HEROES:
        add(f"medal_{h}", "medallions", kind="medallion", hero=h, gold=mg, fractals=mf, icon="shop_medallion",
            desc="Show off who your favorite Hero is for all to see with this Medallion.", priority=3)
    seen = set()
    for i in sorted(cat, key=lambda i: -i["display_priority"]):
        if not i["visible"]:
            continue
        c, name, desc = i["category"], text(i["name"]), text(i["desc"])
        key = (c, name)
        if key in seen:
            continue
        seen.add(key)
        base = {"gold": i["price"], "fractals": i["shard_price"], "priority": i["display_priority"], "source": i["catalog_ownable_id"]}
        if c == "potion" and i["ownable_type_id"] not in POTION_EXCLUDE:
            desc = DESC_OVERRIDE.get(i["ownable_type_id"], desc)
            if BANNED.search(name + " " + desc):
                continue
            icon = exp.get(str(i["ownable_type_id"]), "").split("|")[-1]
            icon = POTION_ICONS.get(icon, re.sub(r"^goody_(effects_)?(.*)_shopping$", r"potion_\2", icon))
            eff = POTION_EFFECTS.get(i["ownable_type_id"])
            add(f"c{i['catalog_ownable_id']}", "potions", kind="potion", name=name, desc=desc, icon=icon,
                effect=eff, soon=eff is None, consumable=True, **base)
        elif c == "title" and name.startswith("The "):
            if name[4:] in TITLE_DENY or BANNED.search(name):
                continue
            add(f"c{i['catalog_ownable_id']}", "titles", kind="title", name=name,
                desc="Let everyone know what your hero is about with this title!", icon="shop_title", **base)
        elif c == "moneybag":
            m = re.search(r"([\d,]+)\s*Fractals", name)
            if m:
                add(f"c{i['catalog_ownable_id']}", "misc", kind="moneybag", name=name, desc=desc, icon="potion_fractal",
                    grant=int(m.group(1).replace(",", "")), consumable=True, **base)
        elif c == "sidekick":
            if name.strip() not in SIDEKICK_ALLOW or BANNED.search(name + " " + desc):
                continue
            add(f"c{i['catalog_ownable_id']}", "sidekicks", kind="sidekick", name=name, desc=desc, icon="shop_sidekick",
                soon=True, **base)
    # "New!": the potions and titles the port added most recently in the original's own priority order
    for iid in [k for k in by_nav["potions"] if not items[k].get("soon")][:6] + by_nav["misc"][:2]:
        by_nav["new"].append(iid)
    for nav in by_nav:
        by_nav[nav].sort(key=lambda k: (-(items[k].get("priority") or 0), items[k].get("name") or items[k]["id"]))
    nav = [{"id": n, "title": t, **({"color": [c[0], c[1], c[2]]} if c else {}), **({"soon": True} if n in SOON else {})}
           for n, t, c in NAV]
    data = {"nav": nav, "items": items, "byNav": by_nav,
            "currencies": {"gold": "Gold", "fractals": "Fractals"}}
    body = "-- generated by tools/convert_store.py from the original store catalog: do not edit\nreturn " + lua(data) + "\n"
    check(body, "StoreData.lua")
    open(os.path.join(root, "studio/game/shared/StoreData.lua"), "w").write(body)
    counts = {n: len(v) for n, v in by_nav.items()}
    print(f"StoreData.lua: {len(items)} items {counts} ({len(body) // 1024} KB); badge tiers {sg}/{sf} and {gg}/{gf}")


if __name__ == "__main__":
    main()
