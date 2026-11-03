"""Minimal reader for Unity text-serialized (YAML) assets, e.g. Unity 3.x asset bundles saved as .asset.

load(path) -> dict fileID -> Obj(cls, cid, fid, data); hex blobs (index buffers, vertex data,
image data) are kept as raw strings in obj.hex[...] so YAML never mangles them into numbers.
"""
import re

import yaml

HEX_KEYS = ("m_IndexBuffer", "_typelessdata", "m_Data")
_hex_re = re.compile(r"^(\s*)(" + "|".join(HEX_KEYS) + r"): ([0-9a-fA-F]*)\s*$", re.M)
_num_re = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


class Obj:
    __slots__ = ("cid", "fid", "cls", "data", "hex")

    def __init__(self, cid, fid, cls, data, hexes):
        self.cid, self.fid, self.cls, self.data, self.hex = cid, fid, cls, data, hexes

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, d=None):
        return self.data.get(k, d)

    def __repr__(self):
        return f"<{self.cls} &{self.fid} {self.data.get('m_Name', '')!r}>"


def _numify(x):
    if isinstance(x, dict):
        return {(_numify(k) if isinstance(k, str) and _num_re.match(k) else k): _numify(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_numify(v) for v in x]
    if isinstance(x, str) and _num_re.match(x):
        return float(x)
    return x


def load(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    parts = re.split(r"^--- !u!(\d+) &(-?\d+)[^\n]*\n", text, flags=re.M)
    objs = {}
    for i in range(1, len(parts), 3):
        cid, fid, body = int(parts[i]), int(parts[i + 1]), parts[i + 2]
        hexes = {}

        def stash(m):
            key = f"__HEX{len(hexes)}__"
            hexes[key] = m.group(3)
            return f"{m.group(1)}{m.group(2)}: {key}"

        body = _hex_re.sub(stash, body)
        doc = yaml.safe_load(body)
        (cls, data), = doc.items()
        data = _numify(data or {})
        objs[fid] = Obj(cid, fid, cls, data, hexes)
    return objs


def hexbytes(obj, value):
    """Resolve a stashed hex placeholder (or empty) to bytes."""
    if isinstance(value, str) and value in obj.hex:
        return bytes.fromhex(obj.hex[value])
    return b""


def ref(x):
    """fileID of a {fileID: N} reference, or 0."""
    if isinstance(x, dict):
        return int(x.get("fileID", 0) or 0)
    return 0


def tex_envs(mat):
    """Material texture slots -> {name: (fileID, scale(x,y), offset(x,y))}, for Unity 3.x and later layouts."""
    envs = mat["m_SavedProperties"].get("m_TexEnvs", {})
    out = {}
    items = []
    if isinstance(envs, dict) and "data" in envs:
        d = envs["data"]
        items = d if isinstance(d, list) else [d]
        for it in items:
            name = it["first"]["name"]
            sec = it["second"]
            out[name] = (ref(sec.get("m_Texture")), sec.get("m_Scale", {}), sec.get("m_Offset", {}))
    elif isinstance(envs, list):
        for it in envs:
            if isinstance(it, dict) and "first" in it:
                out[it["first"]["name"]] = (ref(it["second"].get("m_Texture")), it["second"].get("m_Scale", {}), it["second"].get("m_Offset", {}))
            elif isinstance(it, dict):
                (name, sec), = it.items()
                out[name] = (ref(sec.get("m_Texture")), sec.get("m_Scale", {}), sec.get("m_Offset", {}))
    elif isinstance(envs, dict):
        for name, sec in envs.items():
            out[name] = (ref(sec.get("m_Texture")), sec.get("m_Scale", {}), sec.get("m_Offset", {}))
    return out
