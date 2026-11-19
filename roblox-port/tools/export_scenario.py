"""Export an original brawler scenario bundle (archive Brawler/<name>.asset) to JSON: the tile placements
(ObjectPlaceholders) and every scenario object with its world transform, colliders, renderers, animations,
lights, sounds and the full fields of its scripts (object references resolved to paths or asset names).

Usage: python export_scenario.py <scenario.asset> <out.json>
"""
import json
import math
import sys

import numpy as np

from unity_bundle_tree import Bundle

ASSET_TYPES = {"AudioClip", "Texture2D", "Material", "Mesh", "AnimationClip", "Shader", "MonoScript", "Font",
               "TextAsset", "Cubemap"}


def trs(t):
    p = t["m_LocalPosition"]
    q = t["m_LocalRotation"]
    s = t["m_LocalScale"]
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * np.array([s["x"], s["y"], s["z"]])
    m[:3, 3] = [p["x"], p["y"], p["z"]]
    return m


def mat_to_pqs(m):
    """World 4x4 -> position, rotation quaternion (x,y,z,w), lossy scale (signed: negative det goes on x)."""
    a = m[:3, :3].copy()
    sc = np.linalg.norm(a, axis=0)
    if np.linalg.det(a) < 0:
        sc[0] = -sc[0]
    r = a / np.where(sc == 0, 1, sc)
    tr = r[0, 0] + r[1, 1] + r[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        q = [0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s, (r[2, 1] - r[1, 2]) / s]
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        q = [(r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s, (r[0, 2] - r[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        q = [(r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s, (r[1, 0] - r[0, 1]) / s]
    return [round(float(v), 4) for v in m[:3, 3]], [round(float(v), 5) for v in q], [round(float(v), 4) for v in sc]


class Exporter:
    def __init__(self, path):
        self.b = Bundle(path)
        self.world = {}

    def world_of(self, g):
        if g not in self.world:
            m = trs(self.b.read(self.b.tr_of_go[g]))
            p = self.b.parent.get(g)
            self.world[g] = (self.world_of(p) @ m) if p is not None else m
        return self.world[g]

    def ref(self, v):
        pid = v.get("m_PathID", 0)
        if not pid:
            return None
        if v.get("m_FileID", 0):
            return {"ext": v["m_FileID"], "pid": pid}
        t = self.b.type(pid)
        if t is None:
            return {"missing": pid}
        if t == "GameObject":
            return {"go": self.b.path(pid)}
        if t in ASSET_TYPES:
            return {"asset": t, "name": self.b.read(pid).get("m_Name")}
        d = self.b.read(pid)
        if "m_GameObject" in d:
            g = d["m_GameObject"]["m_PathID"]
            out = {"go": self.b.path(g), "comp": t}
            if t == "MonoBehaviour":
                out["script"] = self.b.script_name(pid)
            return out
        return {"type": t, "pid": pid}

    def clean(self, v):
        if isinstance(v, dict):
            if set(v) >= {"m_FileID", "m_PathID"} and len(v) == 2:
                return self.ref(v)
            return {k: self.clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.clean(x) for x in v]
        if isinstance(v, float):
            return round(v, 5)
        if isinstance(v, (bytes, bytearray)):
            return None
        return v

    def component(self, pid):
        b = self.b
        t = b.type(pid)
        d = b.read(pid)
        out = {"type": t}
        if t == "MonoBehaviour":
            out["script"] = b.script_name(pid)
            out["enabled"] = bool(d.get("m_Enabled", 1))
            out["fields"] = {k: self.clean(v) for k, v in d.items() if not k.startswith("m_")}
        elif t == "BoxCollider":
            out.update(trigger=bool(d.get("m_IsTrigger")), enabled=bool(d.get("m_Enabled", 1)),
                       center=self.clean(d["m_Center"]), size=self.clean(d["m_Size"]))
        elif t == "SphereCollider":
            out.update(trigger=bool(d.get("m_IsTrigger")), center=self.clean(d["m_Center"]), radius=d["m_Radius"])
        elif t == "CapsuleCollider":
            out.update(trigger=bool(d.get("m_IsTrigger")), center=self.clean(d["m_Center"]), radius=d["m_Radius"],
                       height=d["m_Height"], direction=d["m_Direction"])
        elif t == "MeshCollider":
            out.update(trigger=bool(d.get("m_IsTrigger")), convex=bool(d.get("m_Convex")), mesh=self.clean(d["m_Mesh"]))
        elif t == "MeshFilter":
            out["mesh"] = self.clean(d["m_Mesh"])
        elif t in ("MeshRenderer", "SkinnedMeshRenderer"):
            out["enabled"] = bool(d.get("m_Enabled", 1))
            out["materials"] = [self.clean(m) for m in d.get("m_Materials", [])]
            if t == "SkinnedMeshRenderer":
                out["mesh"] = self.clean(d.get("m_Mesh", {}))
        elif t == "Animation":
            out["clip"] = self.clean(d.get("m_Animation", {}))
            out["clips"] = [self.clean(c) for c in d.get("m_Animations", [])]
            out["play"] = bool(d.get("m_PlayAutomatically", 1))
            out["wrap"] = d.get("m_WrapMode", 0)
        elif t == "Light":
            out.update(kind=d.get("m_Type"), color=self.clean(d.get("m_Color")), intensity=d.get("m_Intensity"),
                       range=d.get("m_Range"), spot=d.get("m_SpotAngle"), enabled=bool(d.get("m_Enabled", 1)))
        elif t == "AudioSource":
            out.update(clip=self.clean(d.get("m_audioClip", {})), loop=bool(d.get("m_Loop")),
                       volume=d.get("m_Volume"), play=bool(d.get("m_PlayOnAwake")), enabled=bool(d.get("m_Enabled", 1)))
        elif t == "Rigidbody":
            out.update(kinematic=bool(d.get("m_IsKinematic")), gravity=bool(d.get("m_UseGravity")), mass=d.get("m_Mass"))
        elif t == "TrailRenderer":
            out.update(time=d.get("m_Time"), start=d.get("m_StartWidth"), end=d.get("m_EndWidth"),
                       materials=[self.clean(m) for m in d.get("m_Materials", [])])
        return out

    def export(self, root_name=None):
        b = self.b
        roots = b.roots
        scen = [g for g in roots if b.name(g).endswith("_scenario_Bundle")]
        top = scen[0] if scen else roots[0]
        objs = []
        index = {}
        for g, depth in b.walk(top):
            p, q, s = mat_to_pqs(self.world_of(g))
            index[g] = len(objs)
            objs.append({
                "name": b.name(g), "path": b.path(g), "parent": index.get(b.parent.get(g), -1),
                "active": bool(b.read(g).get("m_IsActive", True)), "layer": b.read(g).get("m_Layer"),
                "tag": b.read(g).get("m_Tag"),
                "pos": p, "rot": q, "scale": s,
                "components": [self.component(pid) for pid in b.components(g) if b.type(pid) != "Transform"],
            })
        tiles = []
        for o in objs:
            for c in o["components"]:
                if c.get("script") == "ObjectPlaceholder":
                    f = c["fields"]
                    tiles.append({"prefab": f["prefabName"], "bundle": f["bundleName"], "parent": f.get("parentName"),
                                  "pos": o["pos"], "rot": o["rot"], "scale": o["scale"], "path": o["path"]})
        prefabs = [b.path(g) for g in roots if g != top]
        audio = {}
        for g in roots:
            for n, pid in b.behaviours(g, "ShsAudioSource"):
                audio[b.name(g)] = self.clean({k: v for k, v in b.read(pid).items() if not k.startswith("m_")})
        return {"scenario": b.name(top).replace("_Bundle", ""), "tiles": tiles, "objects": objs, "prefabs": prefabs,
                "audio_sources": audio}


def main():
    src, out = sys.argv[1:3]
    data = Exporter(src).export()
    with open(out, "w") as f:
        json.dump(data, f, indent=1)
    print(f"{data['scenario']}: {len(data['tiles'])} tiles, {len(data['objects'])} objects -> {out}")


if __name__ == "__main__":
    main()
