"""Port the heroes' visual and sound effects (the original EffectSequence prefabs inside each hero bundle)
to Roblox data, textures and one audio sprite.

Per hero bundle, every EffectSequence (e.g. the L3 swing, an impact, a power emote) becomes an entry of
studio/game/shared/FxData.lua, and the runtime (studio/game/shared/FxPlayer.lua) rebuilds it on the rig:
  legacy particle systems (Ellipsoid/Mesh emitter + ParticleAnimator + ParticleRenderer) -> ParticleEmitter
      (rate/burst, lifetime, size + sizeGrow, 5-key colour/alpha animation, local/world/random velocity,
      force, damping, rotation, additive vs alpha blending, stretched particles, UV flipbooks)
  TrailRenderer -> Trail      Light -> PointLight      LineRenderer -> Beam
  animated FX meshes (rings, cylinders, planes) -> primitive parts with their scale/alpha animation sampled
  sounds (ShsAudioSource clip variations, delays, volume, pitch, distance) -> segments of one audio sprite
Positions are in studs relative to the attach bone (AttachNodeName, or the rig root), Roblox axes.
Names pass through spso_names.clean(); textures are deduplicated by content across heroes.

Usage: python build_fx.py <roblox-port dir> <work_out_dir> Hero=bundle.unity3d [...]
       [--ui-sounds dir_or_wav ...]   extra UI sounds to put in the sprite (keyed by file name)
Outputs: studio/game/shared/FxData.lua, <work_out>/textures/*.png, <work_out>/audio_sprite.ogg,
         <work_out>/fx_manifest.json (textures + sprite for upload)
"""
import argparse
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import UnityPy
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_game_data import to_lua  # noqa: E402
from spso_names import check, clean  # noqa: E402

K = 2.56
FPS = 20


def r4(x):
    return round(float(x), 4)


def rgba(v):
    """legacy ColorRGBA32 (packed uint, r in the low byte) -> [r, g, b, a] 0..1"""
    if isinstance(v, dict) and "rgba" in v:
        v = v["rgba"]
    if isinstance(v, dict):
        return [v.get("r", 1), v.get("g", 1), v.get("b", 1), v.get("a", 1)]
    v = int(v)
    return [(v & 255) / 255, ((v >> 8) & 255) / 255, ((v >> 16) & 255) / 255, ((v >> 24) & 255) / 255]


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def qrot(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return [vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx)]


def v3(d):
    return [d["x"], d["y"], d["z"]]


def to_rbx_vec(v, s=K):  # Unity left-handed -> Roblox (mirror Z), scaled
    return [r4(v[0] * s), r4(v[1] * s), r4(-v[2] * s)]


def to_rbx_quat(q):
    return [r4(-q[0]), r4(-q[1]), r4(q[2]), r4(q[3])]


def hermite(keys, t):
    if not keys:
        return 0.0
    if t <= keys[0]["time"]:
        return keys[0]["value"]
    for a, b in zip(keys, keys[1:]):
        if a["time"] <= t <= b["time"]:
            dt = b["time"] - a["time"]
            if dt <= 0:
                return b["value"]
            u = (t - a["time"]) / dt
            m0, m1 = a["outSlope"] * dt, b["inSlope"] * dt
            if not (math.isfinite(m0) and math.isfinite(m1)):
                return a["value"]
            u2, u3 = u * u, u * u * u
            return (2 * u3 - 3 * u2 + 1) * a["value"] + (u3 - 2 * u2 + u) * m0 + (-2 * u3 + 3 * u2) * b["value"] + (u3 - u2) * m1
    return keys[-1]["value"]


class Bundle:
    def __init__(self, path, hero, out, shared):
        self.env = UnityPy.load(path)
        self.hero, self.out, self.shared = hero, out, shared
        self.objs = {o.path_id: o for o in self.env.objects}
        self.tt_cache, self.script_cache = {}, {}

    def obj(self, ref):
        pid = ref.get("m_PathID", 0) if isinstance(ref, dict) else getattr(ref, "path_id", 0)
        return self.objs.get(pid) if pid else None

    def tt(self, o):
        if o.path_id not in self.tt_cache:
            self.tt_cache[o.path_id] = o.read_typetree()
        return self.tt_cache[o.path_id]

    def script(self, o):
        if o.path_id not in self.script_cache:
            try:
                self.script_cache[o.path_id] = o.read().m_Script.read().m_ClassName
            except Exception:
                self.script_cache[o.path_id] = ""
        return self.script_cache[o.path_id]

    def comps(self, go_obj):
        out = []
        for c in go_obj.read().m_Component:
            ref = c[1] if isinstance(c, (tuple, list)) else getattr(c, "component", c)
            o = self.objs.get(ref.path_id)
            if o is not None:
                out.append(o)
        return out

    # -- textures / materials / audio -----------------------------------------------------------
    def texture(self, ref):
        o = self.obj(ref)
        if o is None:
            return None
        d = o.read()
        try:
            im = d.image
        except Exception:
            return None
        if im is None:
            return None
        im = im.convert("RGBA")
        if max(im.size) > 256:
            im.thumbnail((256, 256), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        data = buf.getvalue()
        sha = hashlib.sha1(data).hexdigest()[:12]
        tex = self.shared["textures"]
        if sha not in tex:
            key = f"fx_{clean(d.m_Name)}_{sha[:4]}".replace(" ", "_")
            check(key, "texture name")
            open(os.path.join(self.out, "textures", key + ".png"), "wb").write(data)
            tex[sha] = {"key": key, "file": f"textures/{key}.png", "size": list(im.size)}
        return tex[sha]["key"]

    def material(self, ref):
        o = self.obj(ref)
        if o is None:
            return {}
        t = self.tt(o)
        shader = ""
        so = self.obj(t.get("m_Shader", {}))
        if so is not None:
            try:
                sd = so.read()
                shader = getattr(sd, "m_Name", "") or ""
                if not shader:
                    src = getattr(sd, "m_Script", "")
                    src = src.decode(errors="ignore") if isinstance(src, (bytes, bytearray)) else str(src)
                    i = src.find('Shader "')
                    shader = src[i + 8: src.find('"', i + 8)] if i >= 0 else ""
            except Exception:
                pass
        props = t.get("m_SavedProperties", {})
        tex = None
        for name, env in props.get("m_TexEnvs", []):
            n = name["name"] if isinstance(name, dict) else name
            if n == "_MainTex":
                tex = self.texture(env["m_Texture"])
        tint = [1, 1, 1, 1]
        for name, col in props.get("m_Colors", []):
            n = name["name"] if isinstance(name, dict) else name
            if n in ("_TintColor", "_Color"):
                tint = [col["r"], col["g"], col["b"], col["a"]]
                if n == "_TintColor":  # Particles/* shaders multiply the tint by 2
                    tint = [min(1, 2 * c) for c in tint]
        sl = shader.lower()
        blend = "add" if ("additive" in sl or "add" in sl.split("/")[-1].lower()) else (
            "premul" if "premultipl" in sl else ("mult" if "multipl" in sl else "alpha"))
        return {"tex": tex, "blend": blend, "tint": [r4(c) for c in tint], "shader": shader}

    def audio(self, ref):
        o = self.obj(ref)
        if o is None:
            return None
        d = o.read()
        key = clean(d.m_Name).replace(" ", "_")
        check(key, "audio name")
        au = self.shared["audio"]
        if key not in au:
            try:
                samples = d.samples
            except Exception as e:
                print("  audio export failed", key, e)
                return None
            if not samples:
                return None
            name, data = next(iter(samples.items()))
            ext = os.path.splitext(name)[1] or ".ogg"
            path = os.path.join(self.out, "audio", key + ext)
            open(path, "wb").write(data)
            au[key] = {"file": path}
        return key

    # -- prefab elements ------------------------------------------------------------------------
    def walk(self, go_obj, pos, rot, scl, elems, depth=0):
        comps = self.comps(go_obj)
        by = {}
        for c in comps:
            by.setdefault(c.type.name, []).append(c)
        tr = by.get("Transform", [None])[0]
        if tr is not None:
            t = self.tt(tr)
            lp, lr, ls = v3(t["m_LocalPosition"]), [t["m_LocalRotation"][k] for k in "xyzw"], v3(t["m_LocalScale"])
            p = qrot(rot, [lp[i] * scl[i] for i in range(3)])
            pos = [pos[i] + p[i] for i in range(3)]
            rot = qmul(rot, lr)
            scl = [scl[i] * ls[i] for i in range(3)]
        base = {"pos": to_rbx_vec(pos), "rot": to_rbx_quat(rot), "scale": r4(sum(abs(s) for s in scl) / 3)}
        em = (by.get("EllipsoidParticleEmitter") or by.get("MeshParticleEmitter") or [None])[0]
        if em is not None:
            e = self.tt(em)
            an = self.tt(by["ParticleAnimator"][0]) if "ParticleAnimator" in by else {}
            rd = self.tt(by["ParticleRenderer"][0]) if "ParticleRenderer" in by else {}
            mat = self.material(rd["m_Materials"][0]) if rd.get("m_Materials") else {}
            if e.get("m_Enabled", True) and mat.get("tex"):
                s = base["scale"]
                cols = [rgba(an[f"colorAnimation[{i}]"]) for i in range(5)] if an.get("Does Animate Color?") else [[1, 1, 1, 1]] * 5
                uv = rd.get("UV Animation", {})
                elems.append(dict(base, kind="emitter", tex=mat["tex"], blend=mat["blend"], tint=mat["tint"],
                                  emit=bool(e.get("m_Emit", True)), oneShot=bool(e.get("m_OneShot")),
                                  size=[r4(e["minSize"] * K * s), r4(e["maxSize"] * K * s)],
                                  energy=[r4(e["minEnergy"]), r4(e["maxEnergy"])],
                                  emission=[r4(e["minEmission"]), r4(e["maxEmission"])],
                                  localVel=to_rbx_vec(v3(e["localVelocity"]), K * s), worldVel=to_rbx_vec(v3(e["worldVelocity"]), K * s),
                                  rndVel=[r4(abs(x) * K * s) for x in v3(e["rndVelocity"])],
                                  tangentVel=to_rbx_vec(v3(e.get("tangentVelocity", {"x": 0, "y": 0, "z": 0})), K * s),
                                  angularVel=r4(e.get("angularVelocity", 0)), rndAngularVel=r4(e.get("rndAngularVelocity", 0)),
                                  rndRotation=bool(e.get("rndRotation")), worldSpace=bool(e.get("Simulate in Worldspace?")),
                                  ellipsoid=[r4(abs(x) * K * s) for x in v3(e.get("m_Ellipsoid", {"x": 0, "y": 0, "z": 0}))],
                                  colors=[[r4(c) for c in col] for col in cols],
                                  sizeGrow=r4(an.get("sizeGrow", 0)), damping=r4(an.get("damping", 1)),
                                  force=to_rbx_vec(v3(an.get("force", {"x": 0, "y": 0, "z": 0})), K * s),
                                  rndForce=[r4(abs(x) * K * s) for x in v3(an.get("rndForce", {"x": 0, "y": 0, "z": 0}))],
                                  stretch=int(rd.get("m_StretchParticles", 0)), lengthScale=r4(rd.get("m_LengthScale", 0)),
                                  velocityScale=r4(rd.get("m_VelocityScale", 0)),
                                  uvTiles=[int(uv.get("x Tile", 1)), int(uv.get("y Tile", 1)), r4(uv.get("cycles", 1))]))
        for trc in by.get("TrailRenderer", []):
            t = self.tt(trc)
            mat = self.material(t["m_Materials"][0]) if t.get("m_Materials") else {}
            if mat.get("tex"):
                s = base["scale"]
                cols = [rgba(t["m_Colors"][f"m_Color[{i}]"]) for i in range(5)]
                elems.append(dict(base, kind="trail", tex=mat["tex"], blend=mat["blend"], tint=mat["tint"], time=r4(t["m_Time"]),
                                  width=[r4(t["m_StartWidth"] * K * s), r4(t["m_EndWidth"] * K * s)],
                                  colors=[[r4(c) for c in col] for col in cols]))
        for lc in by.get("Light", []):
            t = self.tt(lc)
            col = t.get("m_Color", {"r": 1, "g": 1, "b": 1, "a": 1})
            elems.append(dict(base, kind="light", color=[r4(col["r"]), r4(col["g"]), r4(col["b"])],
                              intensity=r4(t.get("m_Intensity", 1)), range=r4(t.get("m_Range", 5) * K)))
        for lc in by.get("LineRenderer", []):
            t = self.tt(lc)
            mat = self.material(t["m_Materials"][0]) if t.get("m_Materials") else {}
            p = t.get("m_Parameters", t)
            elems.append(dict(base, kind="line", tex=mat.get("tex"), blend=mat.get("blend", "add"), tint=mat.get("tint", [1, 1, 1, 1]),
                              width=[r4(p.get("startWidth", 1) * K), r4(p.get("endWidth", 1) * K)],
                              colors=[[r4(c) for c in rgba(p.get("m_StartColor", 0xFFFFFFFF))], [r4(c) for c in rgba(p.get("m_EndColor", 0xFFFFFFFF))]]))
        mr = by.get("MeshRenderer", [None])[0]
        mf = by.get("MeshFilter", [None])[0]
        if mr is not None and mf is not None:
            t = self.tt(mr)
            mat = self.material(t["m_Materials"][0]) if t.get("m_Materials") else {}
            mo = self.obj(self.tt(mf).get("m_Mesh", {}))
            if mo is not None and mat.get("tex"):
                mt = self.tt(mo)
                name = (mt.get("m_Name") or "").lower()
                ext = v3(mt.get("m_LocalAABB", {}).get("m_Extent", {"x": .5, "y": .5, "z": .5}))
                shape = "cylinder" if "cylinder" in name else "plane" if "plane" in name else "sphere" if "sphere" in name else "box"
                el = dict(base, kind="mesh", shape=shape, tex=mat["tex"], blend=mat["blend"], tint=mat["tint"],
                          size=[r4(2 * abs(ext[i]) * abs(scl[i]) * K) for i in range(3)])
                anim = self.sample_anim(by.get("Animation", [None])[0])
                if anim:
                    el["anim"] = anim
                elems.append(el)
        if tr is not None:
            for ch in self.tt(tr).get("m_Children", []):
                co = self.obj(ch)
                if co is not None:
                    go = self.obj(self.tt(co)["m_GameObject"])
                    if go is not None and depth < 8:
                        self.walk(go, pos, rot, scl, elems, depth + 1)

    def sample_anim(self, an):
        """root scale (relative) and material alpha of an FX mesh's first clip, sampled at FPS"""
        if an is None:
            return None
        t = self.tt(an)
        refs = t.get("m_Animations") or []
        co = self.obj(refs[0]) if refs else None
        if co is None:
            return None
        c = self.tt(co)
        length = 0.0
        scale, alpha = None, None
        for sc in c.get("m_ScaleCurves", []):
            if sc.get("path", "") == "":
                keys = sc["curve"]["m_Curve"]
                if keys:
                    length = max(length, keys[-1]["time"])
                    scale = keys
        for fc in c.get("m_FloatCurves", []):
            attr = fc.get("attribute", "")
            if attr.endswith(".a") and "olor" in attr:
                keys = fc["curve"]["m_Curve"]
                if keys:
                    length = max(length, keys[-1]["time"])
                    alpha = keys
        if not (scale or alpha) or length <= 0:
            return None
        n = int(length * FPS) + 1
        ts = [i / FPS for i in range(n)]
        out = {"dt": 1 / FPS, "wrap": int(t.get("m_WrapMode", 0))}
        if scale:
            s0 = [abs(scale[0]["value"][k]) or 1 for k in "xyz"]
            out["scale"] = [[r4(abs(hermite([dict(k_, value=k_["value"][a], inSlope=k_["inSlope"][a], outSlope=k_["outSlope"][a]) for k_ in scale], t_)) / s0[i])
                             for i, a in enumerate("xyz")] for t_ in ts]
        if alpha:
            out["alpha"] = [r4(min(1, max(0, hermite(alpha, t_)))) for t_ in ts]
        return out

    # -- sequences ------------------------------------------------------------------------------
    def sounds(self, ref):
        o = self.obj(ref)
        if o is None:
            return None
        clips, vol, pitch, loop, dmin, dmax = [], 1.0, 1.0, False, 1.0, 500.0
        for c in self.comps(o):
            if c.type.name == "AudioSource":
                t = self.tt(c)
                vol, pitch, loop = t.get("m_Volume", 1), t.get("m_Pitch", 1), bool(t.get("Loop"))
                dmin, dmax = t.get("MinDistance", 1), t.get("MaxDistance", 500)
                k = self.audio(t["m_audioClip"]) if t.get("m_audioClip", {}).get("m_PathID") else None
                if k:
                    clips.append(k)
            elif c.type.name == "MonoBehaviour" and self.script(c) == "ShsAudioSource":
                t = self.tt(c)
                loop = loop or bool(t.get("Loop"))
                for cl in t.get("Clips", []):
                    k = self.audio(cl["Clip"])
                    if k:
                        clips.append(k)
        if not clips:
            return None
        return {"clips": sorted(set(clips)), "volume": r4(vol), "pitch": r4(pitch), "loop": loop,
                "minDist": r4(dmin * K), "maxDist": r4(min(dmax, 120) * K)}

    def sequences(self):
        seqs, prefabs = {}, {}
        for o in self.env.objects:
            if o.type.name != "MonoBehaviour" or self.script(o) != "EffectSequence":
                continue
            t = self.tt(o)
            name = clean(o.read().m_GameObject.read().m_Name)
            parts = []
            for p in t.get("Particles", []):
                po = self.obj(p["ParticlePrefab"])
                if po is None:
                    continue
                pid = f"p{po.path_id}"
                if pid not in prefabs:
                    elems = []
                    self.walk(po, [0, 0, 0], [0, 0, 0, 1], [1, 1, 1], elems)
                    prefabs[pid] = elems
                if not prefabs[pid]:
                    continue
                parts.append({"t": r4(p.get("TimeOffset", 0)), "life": r4(p.get("Lifetime", -1)), "prefab": pid,
                              "node": (p.get("AttachNodeName") or "").strip(), "detached": bool(p.get("DetachedParticle")),
                              "fade": r4(p.get("FadeTime", 0))})
            snds = []
            for s in t.get("Sounds", []):
                sd = self.sounds(s["SoundPrefab"])
                if sd:
                    snds.append(dict(sd, t=r4(s.get("TimeOffset", 0)), chance=r4(s.get("chanceToPlay", 1)), life=r4(s.get("Lifetime", -1))))
            shake = None
            for g in t.get("Generals", []) or []:
                gref = next((v for v in g.values() if isinstance(v, dict) and "m_PathID" in v), {}) if isinstance(g, dict) else {}
                go = self.obj(gref)
                if go is not None:
                    for c in self.comps(go):
                        if c.type.name == "MonoBehaviour" and self.script(c) == "CameraShake":
                            shake = {"t": r4(g.get("TimeOffset", 0))}
            if parts or snds:
                seqs[name] = {"lifetime": r4(t.get("TotalLifetime", -1)), "loop": bool(t.get("Looping")),
                              "fadeParticles": bool(t.get("FadeParticlesOnEnd")), "particles": parts, "sounds": snds}
                if shake:
                    seqs[name]["shake"] = shake
        used = {p["prefab"] for s in seqs.values() for p in s["particles"]}
        return seqs, {k: v for k, v in prefabs.items() if k in used}


def build_sprite(audio, extra, out):
    """concatenate every clip (0.15 s apart) into one OGG; returns {key: [start, duration]}"""
    tmp = tempfile.mkdtemp()
    entries = [(k, v["file"]) for k, v in sorted(audio.items())] + sorted(extra.items())
    wavs, segs, t = [], {}, 0.0
    for i, (k, f) in enumerate(entries):
        w = os.path.join(tmp, f"{i:04d}.wav")
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-ac", "2", "-ar", "44100", "-sample_fmt", "s16", w])
        if r.returncode or not os.path.exists(w):
            continue
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", w],
                                   capture_output=True, text=True).stdout.strip() or 0)
        if dur <= 0:
            continue
        segs[k] = [r4(t), r4(dur)]
        wavs.append(w)
        t += dur + 0.15
        sil = os.path.join(tmp, f"{i:04d}_s.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.15",
                        "-sample_fmt", "s16", sil])
        wavs.append(sil)
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{w}'\n" for w in wavs))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "libvorbis", "-q:a", "4", out], check=True)
    return segs, r4(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("out")
    ap.add_argument("heroes", nargs="+")
    ap.add_argument("--ui-sounds", nargs="*", default=[])
    a = ap.parse_args()
    for d in ("textures", "audio"):
        os.makedirs(os.path.join(a.out, d), exist_ok=True)
    shared = {"textures": {}, "audio": {}}
    data = {"Heroes": {}}
    for spec in a.heroes:
        hero, bundle = spec.split("=", 1)
        b = Bundle(bundle, hero, a.out, shared)
        seqs, prefabs = b.sequences()
        data["Heroes"][hero] = {"sequences": seqs, "prefabs": prefabs}
        kinds = {}
        for els in prefabs.values():
            for e in els:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print(f"{hero:11s} sequences {len(seqs):3d}, prefabs {len(prefabs):3d}, elements {kinds}")
    extra = {}
    for u in a.ui_sounds:
        files = [os.path.join(u, f) for f in sorted(os.listdir(u))] if os.path.isdir(u) else [u]
        for f in files:
            if f.lower().endswith((".wav", ".ogg", ".mp3")):
                k = clean(os.path.splitext(os.path.basename(f))[0]).replace(" ", "_")
                check(k, "ui sound")
                extra[k] = f
    sprite = os.path.join(a.out, "audio_sprite.ogg")
    segs, total = build_sprite(shared["audio"], extra, sprite)
    data["Sounds"] = segs
    data["SpriteLength"] = total
    lua = ("-- GENERATED by tools/build_fx.py from the heroes' original effect sequences. Do not edit by hand.\n"
           "-- Texture and sound keys resolve to asset ids through Assets.lua.\n"
           "return " + to_lua(data) + "\n")
    check(lua, "FxData.lua")
    open(os.path.join(a.port, "studio", "game", "shared", "FxData.lua"), "w").write(lua)
    man = {"textures": sorted(shared["textures"].values(), key=lambda x: x["key"]),
           "sprite": {"file": "audio_sprite.ogg", "length": total, "sounds": len(segs)}}
    json.dump(man, open(os.path.join(a.out, "fx_manifest.json"), "w"), indent=1)
    print(f"textures {len(man['textures'])}, sounds {len(segs)} in a {total:.0f} s sprite "
          f"({os.path.getsize(sprite) / 1e6:.2f} MB), FxData.lua {len(lua) / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
