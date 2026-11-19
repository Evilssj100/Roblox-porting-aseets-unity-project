"""Name hygiene for everything that ships to Roblox: the original data and bundles use the licensed
characters' names (in effect names, clip names, collider names, textures, sounds). Every string that
goes into a Roblox asset or script passes through clean(), and check() fails the build if anything
branded is left.
"""
import re

# source token -> port name (longest first so "ms_marvel" wins over "marvel")
RENAME = [
    ("spider_man", "gecko"), ("spiderman", "gecko"), ("spidey", "gecko"), ("spider", "gecko"),
    ("ms_marvel", "aurora"), ("msmarvel", "aurora"), ("marvel", "aurora"),
    ("super_skrull", "warlord"), ("superskrull", "warlord"), ("skrull", "thug"),
    ("darkhawk", "skyvolt"), ("falcon", "skyvolt"), ("redwing", "hawk"),
    ("she_hulk", "rugida"), ("hulk", "rugido"),
    ("black_panther", "pantera"), ("iron_man", "steelman"), ("ironman", "steelman"),
    ("drdoom", "tyrant"), ("dr_doom", "tyrant"), ("doom", "tyrant"),
    ("wolverine", "clawman"), ("shsu", "game"), ("shs", "game"), ("mshs", "game"),
    # social zones: licensed places and characters in names
    ("daily_bugle", "daily_bulletin"), ("dailybugle", "dailybulletin"), ("bugle", "bulletin"),
    ("aunt_mays", "neighbors"), ("aunt_may", "neighbor"), ("aunt_mae", "neighbor"), ("auntmay", "neighbor"),
    ("auntmae", "neighbor"), ("parker", "post"),
]
BANNED = re.compile(r"hulk|falcon|marvel|spider|spidey|skrull|darkhawk|redwing|panther|iron_?man|doom|wolverine|"
                    r"avenger|gazillion|\bthing\b|thing_|_thing|bugle|parker|aunt_?ma[ey]", re.I)


def clean(s: str) -> str:
    out = s
    for a, b in RENAME:
        out = re.sub(a, b, out, flags=re.I)
    out = re.sub(r"(?i)(^|[_\s])thing(?=$|[_\s\d])", lambda m: m.group(1) + "magmaul", out)
    return out


def check(text: str, where: str = ""):
    m = BANNED.search(text)
    if m:
        a = max(0, m.start() - 40)
        raise SystemExit(f"branded name left in {where}: ...{text[a:m.end() + 40]}...")
