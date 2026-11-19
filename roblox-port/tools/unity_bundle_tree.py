"""Print the GameObject hierarchy of a Unity asset bundle (Unity 3.x archive bundles included) with each
object's components, local transform and the fields of its MonoBehaviours. A quick way to see what a
tile, scenario or prop bundle holds.

Usage: python unity_bundle_tree.py <bundle.asset> [--depth N] [--fields] [--match TEXT] [--materials]
"""
import argparse
import json

import UnityPy


def comp_ptr(c):
    if isinstance(c, (list, tuple)):
        return c[1]["m_PathID"]
    if "second" in c:
        return c["second"]["m_PathID"]
    return c["component"]["m_PathID"]


class Bundle:
    """Typetree view of a bundle: objects by path id, GameObject children, components, script names."""

    def __init__(self, path):
        self.env = UnityPy.load(path)
        self.objs = {o.path_id: o for o in self.env.objects}
        self.tt = {}
        self.scripts = {}
        for o in self.env.objects:
            if o.type.name == "MonoScript":
                d = self.read(o.path_id)
                self.scripts[o.path_id] = d.get("m_ClassName") or d.get("m_Name")
        self.children = {}
        self.go_of_tr = {}
        self.tr_of_go = {}
        for o in self.env.objects:
            if o.type.name == "Transform":
                t = self.read(o.path_id)
                g = t["m_GameObject"]["m_PathID"]
                self.go_of_tr[o.path_id] = g
                self.tr_of_go[g] = o.path_id
        for tid, g in self.go_of_tr.items():
            t = self.read(tid)
            self.children[g] = [self.go_of_tr[c["m_PathID"]] for c in t["m_Children"] if c["m_PathID"] in self.go_of_tr]
        self.parent = {}
        for g, kids in self.children.items():
            for k in kids:
                self.parent[k] = g
        self.roots = [g for g in self.tr_of_go if g not in self.parent]

    def read(self, pid):
        if pid not in self.tt:
            self.tt[pid] = self.objs[pid].read_typetree()
        return self.tt[pid]

    def type(self, pid):
        o = self.objs.get(pid)
        return o.type.name if o is not None else None

    def name(self, g):
        return self.read(g)["m_Name"]

    def components(self, g):
        out = []
        for c in self.read(g)["m_Component"]:
            pid = comp_ptr(c)
            if pid in self.objs:
                out.append(pid)
        return out

    def comp(self, g, typename):
        for pid in self.components(g):
            if self.type(pid) == typename:
                return pid
        return None

    def script_name(self, pid):
        d = self.read(pid)
        return self.scripts.get(d.get("m_Script", {}).get("m_PathID"), "?")

    def behaviours(self, g, script=None):
        out = []
        for pid in self.components(g):
            if self.type(pid) == "MonoBehaviour":
                n = self.script_name(pid)
                if script is None or n == script:
                    out.append((n, pid))
        return out

    def path(self, g):
        parts = []
        while g is not None:
            parts.append(self.name(g))
            g = self.parent.get(g)
        return "/" + "/".join(reversed(parts))

    def walk(self, g=None, depth=0):
        if g is None:
            for r in self.roots:
                yield from self.walk(r, 0)
            return
        yield g, depth
        for k in self.children.get(g, []):
            yield from self.walk(k, depth + 1)


SKIP = {"m_GameObject", "m_Enabled", "m_Script", "m_Name", "m_EditorHideFlags", "m_ObjectHideFlags",
        "m_PrefabParentObject", "m_PrefabInternal", "m_EditorClassIdentifier"}


def short(v):
    if isinstance(v, dict) and set(v) >= {"m_FileID", "m_PathID"}:
        return f"->{v['m_PathID']}" if v["m_PathID"] else None
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, dict):
        return {k: short(x) for k, x in v.items()}
    if isinstance(v, list):
        return [short(x) for x in v[:12]] + (["..."] if len(v) > 12 else [])
    return v


def fields(b, pid):
    d = b.read(pid)
    return {k: short(v) for k, v in d.items() if k not in SKIP}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--depth", type=int, default=99)
    ap.add_argument("--fields", action="store_true")
    ap.add_argument("--match", default=None)
    ap.add_argument("--materials", action="store_true")
    a = ap.parse_args()
    b = Bundle(a.bundle)
    for g, depth in b.walk():
        if depth > a.depth:
            continue
        p = b.path(g)
        if a.match and a.match.lower() not in p.lower():
            continue
        t = b.read(b.tr_of_go[g])
        pos = tuple(round(t["m_LocalPosition"][k], 2) for k in "xyz")
        comps = []
        for pid in b.components(g):
            tn = b.type(pid)
            if tn == "Transform":
                continue
            comps.append(b.script_name(pid) if tn == "MonoBehaviour" else tn)
        active = "" if b.read(g).get("m_IsActive", True) else " (inactive)"
        print("  " * depth + f"{b.name(g)}{active} {pos} [{', '.join(comps)}]")
        if a.fields:
            for n, pid in b.behaviours(g):
                print("  " * depth + f"    {n}: {json.dumps(fields(b, pid), default=str)[:600]}")
    if a.materials:
        for o in b.env.objects:
            if o.type.name == "Material":
                d = b.read(o.path_id)
                sh = d["m_Shader"]["m_PathID"]
                shn = b.read(sh).get("m_Name") if sh in b.objs else f"ext:{d['m_Shader']['m_FileID']}"
                print("MAT", d["m_Name"], "|", shn)


if __name__ == "__main__":
    main()
