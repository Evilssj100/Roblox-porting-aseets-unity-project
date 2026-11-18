"""Repurpose the original heroes' textures into ORIGINAL characters, in bulk.

Each recipe keeps the painted shading of the original texture (luminance) and replaces what identifies
the franchise character: emblems and patterns are inpainted away, costume colors are repainted with
new gradients, and new original details (emblems, stripes) are painted using the per-texel position /
normal / bone maps from uv_bake_maps.py.

Outputs per hero: <out>/<Hero>/<Hero>_Body.png and <Hero>_HeadAtlas.png (4x2 expression tiles; tiles the
original lacks are filled with tile 0), plus <Hero>_textures.png (before/after sheet).
Usage: python repurpose_heroes.py <work_heroes_dir> <out_dir> [Hero ...]
"""
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255


def grad(t, stops):
    t = np.clip(t, 0, 1)
    xs = np.array([s[0] for s in stops])
    cs = np.stack([hexrgb(s[1]) for s in stops])
    return np.stack([np.interp(t, xs, cs[:, k]) for k in range(3)], -1)


def hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    sd = np.where(d > 0, d, 1)
    h = np.where(mx == r, ((g - b) / sd) % 6, np.where(mx == g, (b - r) / sd + 2, (r - g) / sd + 4)) / 6
    h = np.where(d > 0, h, 0)
    s = np.where(mx > 0, d / np.where(mx > 0, mx, 1), 0)
    return h, s, mx


def lum(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114], np.float32)


def hue_in(h, a, b):
    return (h >= a) & (h <= b) if a <= b else (h >= a) | (h <= b)


class Tex:
    """a texture with optional texel maps (pos / nrm / bone) from uv_bake_maps.py"""

    def __init__(self, maps_dir, name, bones=None):
        self.rgb = np.asarray(Image.open(os.path.join(maps_dir, name + ".png")).convert("RGB"), np.float32) / 255
        self.orig = self.rgb.copy()
        p = os.path.join(maps_dir, name + "__pos.npy")
        self.pos = np.load(p) if os.path.exists(p) else None
        self.nrm = np.load(os.path.join(maps_dir, name + "__nrm.npy")) if self.pos is not None else None
        self.bone = np.load(os.path.join(maps_dir, name + "__bone.npy")) if self.pos is not None else None
        self.names = bones or []

    @property
    def hsv(self):
        return hsv(self.rgb)

    def bones(self, *prefixes):
        if self.bone is None:
            return np.ones(self.rgb.shape[:2], bool)
        ids = [i for i, n in enumerate(self.names) if any(n.startswith(p) for p in prefixes)]
        return np.isin(self.bone, ids)

    def inpaint(self, mask, grow=2, radius=6):
        m = ndi.binary_dilation(mask, iterations=grow) if grow else mask
        img = (np.clip(self.rgb, 0, 1) * 255 + 0.5).astype(np.uint8)
        out = cv2.inpaint(img, m.astype(np.uint8) * 255, radius, cv2.INPAINT_TELEA)
        self.rgb = out.astype(np.float32) / 255

    def repaint(self, mask, stops, lo=2, hi=98, lift=0.0):
        """luminance-preserving repaint: luminance (normalised inside the mask) -> gradient"""
        if not mask.any():
            return
        L = lum(self.rgb)
        a, b = np.percentile(L[mask], [lo, hi])
        t = np.clip((L - a) / max(b - a, 1e-4) + lift, 0, 1)
        self.rgb[mask] = grad(t, stops)[mask]

    def front_point(self, bone_prefixes, z_quantile=0.72):
        """pixel (row, col) on the front of the given bones' surface, centred left-right, plus px per unit"""
        m = self.bones(*bone_prefixes) & np.isfinite(self.pos[..., 0])
        m &= self.nrm[..., 1] < -0.6  # Blender: model faces -Y
        rows, cols = np.nonzero(m)
        P = self.pos[rows, cols]
        z = np.quantile(P[:, 2], z_quantile)
        score = np.abs(P[:, 0]) + 0.5 * np.abs(P[:, 2] - z)
        i = int(np.argmin(score))
        r, c = rows[i], cols[i]
        # texel density around the point (pixels per model unit)
        r2, c2 = min(r + 4, self.rgb.shape[0] - 1), min(c + 4, self.rgb.shape[1] - 1)
        d = np.linalg.norm(self.pos[r2, c2] - self.pos[r, c]) if np.isfinite(self.pos[r2, c2, 0]) else 0.0
        ppu = (4 * math.sqrt(2)) / d if d > 1e-6 else 200.0
        return r, c, ppu

    def stamp(self, center, size_px, shape, fill, outline=None, rot=0.0):
        """antialiased original emblem: star4 / star5 / chevron / diamond / ring"""
        S = 4
        n = int(size_px * 2.4) + 4
        im = Image.new("L", (n * S, n * S), 0)
        d = ImageDraw.Draw(im)
        cx = cy = n * S / 2
        R = size_px * S

        def poly(points):
            return [(cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot)) for x, y in points]

        if shape in ("star4", "star5"):
            k = 4 if shape == "star4" else 5
            pts = []
            for i in range(2 * k):
                a = -math.pi / 2 + i * math.pi / k
                rr = R if i % 2 == 0 else R * (0.32 if k == 4 else 0.42)
                pts.append((rr * math.cos(a), rr * math.sin(a)))
            d.polygon(poly(pts), fill=255)
        elif shape == "chevron":
            w = R * 0.32
            d.polygon(poly([(-R, -R * 0.35), (0, R * 0.45), (R, -R * 0.35), (R, -R * 0.35 + w), (0, R * 0.45 + w), (-R, -R * 0.35 + w)]), fill=255)
            d.polygon(poly([(-R * 0.62, -R * 0.75), (0, -R * 0.05), (R * 0.62, -R * 0.75), (R * 0.62, -R * 0.75 + w * 0.8),
                            (0, -R * 0.05 + w * 0.8), (-R * 0.62, -R * 0.75 + w * 0.8)]), fill=255)
        elif shape == "diamond":
            d.polygon(poly([(0, -R), (R * 0.62, 0), (0, R), (-R * 0.62, 0)]), fill=255)
            d.polygon(poly([(0, -R * 0.45), (R * 0.28, 0), (0, R * 0.45), (-R * 0.28, 0)]), fill=0)
        elif shape == "ring":
            d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
            d.ellipse([cx - R * 0.62, cy - R * 0.62, cx + R * 0.62, cy + R * 0.62], fill=0)
        a = np.asarray(im.resize((n, n), Image.LANCZOS), np.float32) / 255
        r0, c0 = int(center[0] - n / 2), int(center[1] - n / 2)
        H, W = self.rgb.shape[:2]
        rs, cs = slice(max(r0, 0), min(r0 + n, H)), slice(max(c0, 0), min(c0 + n, W))
        a = a[rs.start - r0:rs.stop - r0, cs.start - c0:cs.stop - c0]
        region = self.rgb[rs, cs]
        shade = lum(self.orig[rs, cs])
        shade = np.clip(0.75 + 0.5 * (shade - shade.mean()), 0.6, 1.15)[..., None]
        col = hexrgb(fill)[None, None, :] * shade
        if outline:
            edge = np.clip(ndi.grey_dilation(a, size=3) - a, 0, 1)[..., None]
            region[:] = region * (1 - edge) + hexrgb(outline)[None, None, :] * edge
        region[:] = region * (1 - a[..., None]) + col * a[..., None]

    def save(self, path):
        Image.fromarray((np.clip(self.rgb, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path)


def fill_missing_tiles(atlas):
    """expression tiles the original atlas lacks (black) -> copy of tile 0"""
    H, W = atlas.rgb.shape[:2]
    th, tw = H // 2, W // 4
    t0 = atlas.rgb[0:th, 0:tw].copy()
    for k in range(8):
        r, c = (k // 4) * th, (k % 4) * tw
        tile = atlas.orig[r:r + th, c:c + tw]
        if tile.mean() < 0.02 or tile.std() < 0.03:
            atlas.rgb[r:r + th, c:c + tw] = t0


def small_components(mask, max_px):
    lab, n = ndi.label(mask)
    if n == 0:
        return np.zeros_like(mask)
    sizes = ndi.sum(mask, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes <= max_px
    return keep[lab]


# ------------------------------------------------------------------------------------------- recipes
TEAL = [(0, "#03110F"), (0.4, "#0B3B36"), (0.72, "#177567"), (1, "#7BE3CF")]
BRONZE = [(0, "#2E1A06"), (0.35, "#83551B"), (0.62, "#C98E3A"), (0.85, "#F0C674"), (1, "#FFF2CC")]
ORANGE = [(0, "#4A1C00"), (0.5, "#E0661A"), (1, "#FFD39A")]
VIOLET = [(0, "#0A0418"), (0.4, "#2A1458"), (0.75, "#5A35B0"), (1, "#C2ADFF")]
AQUA = [(0, "#00262A"), (0.4, "#006D75"), (0.75, "#26C2C8"), (1, "#C4FFF9")]
INK_HAIR = [(0, "#04050B"), (0.45, "#161E3A"), (0.75, "#30457F"), (1, "#8CAEF0")]
BASALT = [(0, "#0A0909"), (0.35, "#2A2423"), (0.62, "#4A4240"), (0.85, "#716865"), (1, "#A0958F")]
LAVA = [(0, "#5A0A00"), (0.45, "#E2420C"), (0.8, "#FF9A2A"), (1, "#FFE08A")]
CHARCOAL = [(0, "#050505"), (0.5, "#1E1A1A"), (0.8, "#3A302C"), (1, "#7A6A60")]
NIGHT = [(0, "#020403"), (0.5, "#0E1A12"), (0.82, "#1F3527"), (1, "#4C6E57")]
NEON = [(0, "#0A3A12"), (0.5, "#38D24C"), (1, "#D2FFA0")]
VENOM_EYE = [(0, "#3A4A00"), (0.55, "#C8F000"), (1, "#FAFFC0")]
MEMBRANE = [(0, "#050A06"), (0.6, "#1A3A22"), (1, "#5C8A66")]


def region(tex, r0, r1, c0, c1):
    """mask of a pixel rectangle given as fractions of the texture size"""
    H, W = tex.rgb.shape[:2]
    m = np.zeros((H, W), bool)
    m[int(r0 * H):int(r1 * H), int(c0 * W):int(c1 * W)] = True
    return m


def recipe_skyvolt(body, head):
    h, s, v = body.hsv
    wings = (body.bones("LArmWing", "RArmWing") | region(body, 0, 0.43, 0.55, 1.0)) & (s < 0.3) & (v > 0.35)
    body.inpaint(hue_in(h, 0.78, 0.98) & (s > 0.35) & (v > 0.3), grow=3)  # remove the energy glyphs
    h, s, v = body.hsv
    body.repaint(wings, BRONZE)
    suit = ~wings & (v < 0.75)
    body.repaint(suit, TEAL, lift=0.05)
    legs = body.bones("LLeg", "RLeg") & np.isfinite(body.pos[..., 0])
    side = legs & (np.abs(body.nrm[..., 0]) > 0.93)
    body.repaint(side, ORANGE)
    r, c, ppu = body.front_point(("Ribcage",))
    body.stamp((r, c), 0.13 * ppu, "chevron", "#F2B33D", outline="#1B0F02")
    # head: the white hood/goggle mask -> teal, eyes (small white blobs) kept
    h, s, v = head.hsv
    white = (s < 0.14) & (v > 0.72)
    eyes = small_components(white, max_px=int(0.004 * white.size))
    head.repaint(white & ~eyes, [(0, "#0B3B36"), (0.6, "#177567"), (1, "#9BF0DE")], lo=0, hi=100)
    fill_missing_tiles(head)


def recipe_aurora(body, head):
    h, s, v = body.hsv
    torso = body.bones("Ribcage", "Spine", "Pelvis")
    body.inpaint(torso & hue_in(h, 0.09, 0.2) & (s > 0.45) & (v > 0.5), grow=3)  # chest emblem
    h, s, v = body.hsv
    hair = hue_in(h, 0.07, 0.2) & (s > 0.2) & (v > 0.12)  # the emblem is gone, so every yellow is hair
    body.repaint(hair, INK_HAIR)
    red = hue_in(h, 0.94, 0.04) & (s > 0.45)
    body.repaint(red, AQUA)
    navy = hue_in(h, 0.52, 0.8) & (s > 0.12)
    body.repaint(navy, VIOLET, lift=0.05)
    r, c, ppu = body.front_point(("Ribcage",))
    body.stamp((r, c), 0.12 * ppu, "star4", "#F4FBFF", outline="#120A2A")
    h, s, v = head.hsv
    head.repaint(hue_in(h, 0.52, 0.8) & (s > 0.2), VIOLET, lift=0.1)  # mask
    fill_missing_tiles(head)


def lava_rock(tex, mask):
    L = lum(tex.rgb)
    blur = ndi.gaussian_filter(L, 3)
    crack = np.clip((blur - L) / 0.07, 0, 1)
    a, b = np.percentile(L[mask], [2, 98])
    base = grad((L - a) / max(b - a, 1e-4), BASALT)
    glow = grad(crack, LAVA)
    out = base * (1 - crack[..., None]) + glow * crack[..., None]
    tex.rgb[mask] = out[mask]


def recipe_magmaul(body, head):
    h, s, v = body.hsv
    pelvis = body.bones("Pelvis", "Spine")
    logo = pelvis & (((s < 0.25) & (v > 0.7)) | (hue_in(h, 0.5, 0.7) & (s > 0.35) & (v > 0.55)))
    logo = ndi.binary_closing(logo, iterations=2) & small_components(logo, max_px=int(0.002 * logo.size))
    body.inpaint(logo, grow=3)
    h, s, v = body.hsv
    trunks = hue_in(h, 0.5, 0.72) & (s > 0.3)
    body.repaint(trunks, CHARCOAL)
    rock = hue_in(h, 0.02, 0.16) & (s > 0.3)
    lava_rock(body, rock)
    r, c, ppu = body.front_point(("Pelvis",), z_quantile=0.85)
    body.stamp((r, c), 0.09 * ppu, "ring", "#FF7A1A", outline="#2A0A00")
    h, s, v = head.hsv
    eyes = hue_in(h, 0.52, 0.75) & (s > 0.25)
    mouth = hue_in(h, 0.93, 0.03) & (s > 0.3) & (v > 0.35)
    head.repaint(eyes, [(0, "#3A1000"), (0.6, "#FF7A00"), (1, "#FFE08A")], lo=0, hi=100)
    head.repaint(mouth, [(0, "#1A0200"), (1, "#8A1A08")])
    lava_rock(head, hue_in(h, 0.02, 0.16) & (s > 0.3) & ~eyes & ~mouth)
    fill_missing_tiles(head)


def recipe_nightgecko(body, head):
    h, s, v = body.hsv
    web = hue_in(h, 0.01, 0.13) & (s > 0.4) & (v > 0.3)
    blue = hue_in(h, 0.5, 0.72) & (s > 0.3) & (v > 0.2)
    body.inpaint(web | blue, grow=3, radius=7)
    h, s, v = body.hsv
    grey = (s < 0.15) & (v > 0.3) & body.bones("LArm1", "RArm1", "Ribcage", "LArmCollarbone", "RArmCollarbone")
    grey = ndi.binary_closing(grey, iterations=4)
    flat = ndi.gaussian_filter(lum(body.rgb), 6)  # flatten the web-shaped membrane
    body.rgb[grey] = grad((flat[grey] - flat[grey].min()) / max(np.ptp(flat[grey]), 1e-4), MEMBRANE)
    dark = ~grey
    body.repaint(dark, NIGHT, lift=0.05)
    limbs = body.bones("LLeg", "RLeg", "LArm2", "RArm2", "LArm1", "RArm1", "Spine", "Ribcage") & np.isfinite(body.pos[..., 0])
    side = limbs & (np.abs(body.nrm[..., 0]) > 0.94)
    body.repaint(side, NEON)
    r, c, ppu = body.front_point(("Ribcage",))
    body.stamp((r, c), 0.12 * ppu, "diamond", "#4BE65E", outline="#03140A")
    h, s, v = head.hsv
    head.inpaint(hue_in(h, 0.01, 0.13) & (s > 0.4) & (v > 0.3), grow=2, radius=6)
    h, s, v = head.hsv
    eyes = (s < 0.2) & (v > 0.7)
    head.repaint(eyes, VENOM_EYE, lo=0, hi=100)
    head.repaint(~eyes, NIGHT, lift=0.05)
    fill_missing_tiles(head)


HEROES = {
    "Skyvolt": ("darkhawk", "Falcon_01_Head", recipe_skyvolt),
    "Aurora": ("Ms_Marvel_02", "Ms_Marvel_01_Head", recipe_aurora),
    "Magmaul": ("Thing", "Thing_01_Head", recipe_magmaul),
    "NightGecko": ("spiderman_swUpd", "spiderman_SW2_headUpd", recipe_nightgecko),
}

if __name__ == "__main__":
    work, out = sys.argv[1], sys.argv[2]
    which = sys.argv[3:] or list(HEROES)
    for hero in which:
        bname, hname, recipe = HEROES[hero]
        maps = os.path.join(work, hero, "maps")
        names = [b["name"] for b in json.load(open(os.path.join(maps, "bones.json")))["bones"]]
        body, head = Tex(maps, bname, names), Tex(maps, hname, names)
        recipe(body, head)
        od = os.path.join(out, hero)
        os.makedirs(od, exist_ok=True)
        body.save(os.path.join(od, f"{hero}_Body.png"))
        head.save(os.path.join(od, f"{hero}_HeadAtlas.png"))
        S = 512
        sheet = Image.new("RGB", (S * 4, S), (20, 20, 20))
        for i, arr in enumerate([body.orig, body.rgb]):
            sheet.paste(Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).resize((S, S)), (i * S, 0))
        for i, arr in enumerate([head.orig, head.rgb]):
            im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).resize((S, S // 2))
            sheet.paste(im, (2 * S + i * S, S // 4))
        sheet.save(os.path.join(od, f"{hero}_textures.png"))
        print(hero, "done")
