"""Index unnamed archive bundles (Assets/Unrenamed/CustomAssetBundle-<hash>.asset): for each bundle, its
asset-bundle container names (the names the game loads), root GameObjects, audio clips and textures, so the
missing character, FX and audio bundles can be found by name.

Usage: python index_bundles.py <dir> <out.json>
"""
import json
import os
import sys

import UnityPy

src, out = sys.argv[1:3]
index = {}
for fn in sorted(os.listdir(src)):
    p = os.path.join(src, fn)
    try:
        env = UnityPy.load(p)
    except Exception as e:  # noqa: BLE001
        index[fn] = {"error": str(e)[:200]}
        continue
    info = {"size": os.path.getsize(p), "container": [], "roots": [], "audio": [], "types": {}}
    trs = {}
    for o in env.objects:
        t = o.type.name
        info["types"][t] = info["types"].get(t, 0) + 1
        try:
            if t == "AssetBundle":
                d = o.read_typetree()
                info["container"] = sorted({c[0] if isinstance(c, (list, tuple)) else c.get("first") for c in d.get("m_Container", [])})[:400]
                info["bundle_name"] = d.get("m_Name")
            elif t == "AudioClip":
                info["audio"].append(o.read_typetree().get("m_Name"))
            elif t == "Transform":
                d = o.read_typetree()
                if not d.get("m_Father", {}).get("m_PathID"):
                    trs[o.path_id] = d["m_GameObject"]["m_PathID"]
        except Exception:  # noqa: BLE001
            pass
    objs = {o.path_id: o for o in env.objects}
    for tid, gid in trs.items():
        try:
            info["roots"].append(objs[gid].read_typetree()["m_Name"])
        except Exception:  # noqa: BLE001
            pass
    info["roots"] = sorted(info["roots"])[:200]
    index[fn] = info
json.dump(index, open(out, "w"), indent=1)
print(len(index), "bundles indexed")
