"""Write roblox-port/studio/manifest.json for studio/install.lua.

Conventions (file -> Roblox):
  studio/runtime/<Name>.lua                -> ReplicatedStorage/SPSO/Runtime/<Name>      ModuleScript
  studio/game/shared/<Name>.lua            -> ReplicatedStorage/SPSO/Game/<Name>         ModuleScript
  studio/game/server/<Name>.server.lua     -> ServerScriptService/SPSO/<Name>            Script
  studio/game/client/<Name>.client.lua     -> StarterPlayer/StarterPlayerScripts/<Name>  LocalScript
  studio/game/character/<Name>.client.lua  -> StarterPlayer/StarterCharacterScripts/<Name> LocalScript
  studio/game/character/<Name>.server.lua  -> StarterPlayer/StarterCharacterScripts/<Name> Script
  studio/setup/*.lua                       -> setup steps, run in name order
  heroes/<Hero>/runtime/<Hero>.spsohero.b64 -> hero packs
Usage: python build_studio_manifest.py [roblox-port dir]
"""
import hashlib
import json
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RULES = [("studio/runtime", ".lua", "ReplicatedStorage/SPSO/Runtime", "ModuleScript"),
         ("studio/game/shared", ".lua", "ReplicatedStorage/SPSO/Game", "ModuleScript"),
         ("studio/game/server", ".server.lua", "ServerScriptService/SPSO", "Script"),
         ("studio/game/client", ".client.lua", "StarterPlayer/StarterPlayerScripts", "LocalScript"),
         ("studio/game/character", ".client.lua", "StarterPlayer/StarterCharacterScripts", "LocalScript"),
         ("studio/game/character", ".server.lua", "StarterPlayer/StarterCharacterScripts", "Script")]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


man = {"scripts": [], "heroes": [], "setup": []}
for d, ext, parent, cls in RULES:
    full = os.path.join(ROOT, d)
    if not os.path.isdir(full):
        continue
    for fn in sorted(os.listdir(full)):
        if not fn.endswith(ext) or (ext == ".lua" and (fn.endswith(".server.lua") or fn.endswith(".client.lua"))):
            continue
        rel = f"{d}/{fn}"
        man["scripts"].append({"path": rel, "parent": parent, "name": fn[: -len(ext)], "class": cls, "sha": sha(os.path.join(ROOT, rel))})
setup = os.path.join(ROOT, "studio/setup")
if os.path.isdir(setup):
    man["setup"] = [f"studio/setup/{fn}" for fn in sorted(os.listdir(setup)) if fn.endswith(".lua")]
heroes = os.path.join(ROOT, "heroes")
for h in sorted(os.listdir(heroes)) if os.path.isdir(heroes) else []:
    p = os.path.join(heroes, h, "runtime", f"{h}.spsohero.b64")
    if os.path.exists(p):
        man["heroes"].append({"name": h, "path": f"heroes/{h}/runtime/{h}.spsohero.b64", "sha": sha(p)})
json.dump(man, open(os.path.join(ROOT, "studio/manifest.json"), "w"), indent=1)
print(f"manifest: {len(man['scripts'])} scripts, {len(man['heroes'])} hero packs, {len(man['setup'])} setup steps")
