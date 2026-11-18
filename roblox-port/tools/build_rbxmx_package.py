"""Bundle everything in studio/manifest.json into one Roblox model file (studio/SPSO_Package.rbxmx):
scripts with their Source, hero packs as base64 StringValue chunks, setup ModuleScripts.

Why: the Studio MCP cannot reach GitHub (HTTP allowlist), but a model asset can be uploaded from the
user's Blender (Roblox Uploader add-on credentials) and inserted in Studio. Layout inside the model:
  SPSO_Package (Folder)
    "<Service>/<path>" (Folder, one per destination)  -> its children replace same-named children there
Unpack in Studio with studio/unpack.lua (also shipped as ServerStorage/SPSO/Tools/Unpack).
Hero packs are large and rarely change, so they ship as separate data packages:
  python build_rbxmx_package.py <roblox-port dir> <label>                    code package (scripts, setup, tools)
  python build_rbxmx_package.py <roblox-port dir> <label> --heroes H1,H2     studio/packages/Hero_<H>.rbxmx each
"""
import json
import os
import sys
from xml.sax.saxutils import escape

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COMMIT = sys.argv[2] if len(sys.argv) > 2 else ""
HEROES = sys.argv[sys.argv.index("--heroes") + 1].split(",") if "--heroes" in sys.argv else None
man = json.load(open(os.path.join(ROOT, "studio/manifest.json")))
ref = [0]


def rid():
    ref[0] += 1
    return f"RBX{ref[0]:06d}"


def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def item(cls, name, props="", children=""):
    return (f'<Item class="{cls}" referent="{rid()}"><Properties><string name="Name">{escape(name)}</string>{props}'
            f"</Properties>{children}</Item>")


def hero_items(h):
    b64 = open(os.path.join(ROOT, h["path"])).read().strip()
    CH = 190000
    chunks = "".join(item("StringValue", f"{n + 1:03d}", f'<string name="Value">{b64[i:i + CH]}</string>')
                     for n, i in enumerate(range(0, len(b64), CH)))
    n = (len(b64) + CH - 1) // CH
    meta = item("StringValue", "_meta", f'<string name="Value">{escape(json.dumps({"chunks": n, "bytes": len(b64), "sha": h["sha"]}))}</string>')
    return item("Folder", "Pack", "", meta + chunks)


def write(dests, out):
    version = item("StringValue", "_version", f'<string name="Value">{escape(COMMIT)}</string>')
    body = version + "".join(item("Folder", d, "", "".join(kids)) for d, kids in dests.items())
    xml = ('<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4"><External>null</External><External>nil</External>'
           + item("Folder", "SPSO_Package", "", body) + "</roblox>")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(xml)
    print(f"{out}: {len(xml) / 1e6:.2f} MB, destinations {list(dests)}")


if HEROES:
    for h in man.get("heroes", []):
        if h["name"] in HEROES:
            write({f"ReplicatedStorage/SPSO/Heroes/{h['name']}": [hero_items(h)]},
                  os.path.join(ROOT, "studio", "packages", f"Hero_{h['name']}.rbxmx"))
    sys.exit(0)
dests = {}
for f in man["scripts"]:
    src = open(os.path.join(ROOT, f["path"]), encoding="utf-8").read()
    props = f'<ProtectedString name="Source">{cdata(src)}</ProtectedString>'
    dests.setdefault(f["parent"], []).append(item(f["class"], f["name"], props))
for i, s_ in enumerate(man.get("setup", [])):
    src = open(os.path.join(ROOT, s_), encoding="utf-8").read()
    name = os.path.splitext(os.path.basename(s_))[0]
    dests.setdefault("ServerStorage/SPSO/Setup", []).append(
        item("ModuleScript", name, f'<ProtectedString name="Source">{cdata(src)}</ProtectedString>'))
unpack = os.path.join(ROOT, "studio/unpack.lua")
if os.path.exists(unpack):
    dests.setdefault("ServerStorage/SPSO/Tools", []).append(
        item("ModuleScript", "Unpack", f'<ProtectedString name="Source">{cdata(open(unpack).read())}</ProtectedString>'))
out = os.path.join(ROOT, "studio/SPSO_Package.rbxmx")
write(dests, out)
