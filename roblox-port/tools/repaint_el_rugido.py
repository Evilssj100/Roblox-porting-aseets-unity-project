"""Repaint the brute hero's textures into El Rugido, an original lion-luchador design.

Keeps the original UV layout and painted shading (luminance), and repaints by region:
skin, mask (all 8 expression tiles), mane, trunks with gold belt and hem trim, boots,
wrist tape, gold armlets, amber eyes, plus a belt-buckle emblem in free texture space.

Inputs come from uv_bake_maps.py (work dir). Writes el_rugido_body.png, el_rugido_head.png,
el_rugido_meta.json (belt height, buckle UV square) into the same dir.

Usage: python repaint_el_rugido.py <work_dir>
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as ndi

WD = sys.argv[1]
BODY, HEAD = "Hulk_Gray", "Hulk_Gray_Head"


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255


def grad(t, stops):
    t = np.clip(t, 0, 1)
    xs = np.array([s[0] for s in stops])
    cs = np.stack([hexrgb(s[1]) for s in stops])
    return np.stack([np.interp(t, xs, cs[:, k]) for k in range(3)], axis=-1)


SKIN = [(0.0, "#2E170B"), (0.25, "#5C331C"), (0.45, "#8E5634"), (0.62, "#B9804F"), (0.8, "#E2AE7E"), (1.0, "#FFE0BF")]
CRIMSON = [(0.0, "#1E0206"), (0.3, "#6E0A1C"), (0.5, "#A8132E"), (0.7, "#D8263F"), (0.9, "#FF6E6E"), (1.0, "#FFB3A8")]
GOLD = [(0.0, "#3A2104"), (0.3, "#8A5A12"), (0.5, "#C98E22"), (0.7, "#EEC14A"), (0.9, "#FFE89A"), (1.0, "#FFFBE0")]
MANE = [(0.0, "#5A1802"), (0.3, "#A43C0A"), (0.55, "#E06A16"), (0.8, "#F7A733"), (1.0, "#FFE27A")]
TAPE = [(0.0, "#6F6A62"), (0.4, "#B9B4AA"), (0.7, "#E9E6DF"), (1.0, "#FFFFFF")]
AMBER = [(0.0, "#3A1A00"), (0.45, "#B86A0E"), (0.75, "#F2A93B"), (1.0, "#FFE08A")]


def lum(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rc = np.where(m, (mx - r) / np.where(m, d, 1), 0)
    gc = np.where(m, (mx - g) / np.where(m, d, 1), 0)
    bc = np.where(m, (mx - b) / np.where(m, d, 1), 0)
    h = np.where(r == mx, bc - gc, np.where(g == mx, 2.0 + rc - bc, 4.0 + gc - rc))
    h = (h / 6.0) % 1.0
    h[~m] = 0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def load(name):
    img = np.asarray(Image.open(os.path.join(WD, f"{name}.png")).convert("RGB")).astype(np.float32) / 255
    pos = np.load(os.path.join(WD, f"{name}__pos.npy"))
    nrm = np.load(os.path.join(WD, f"{name}__nrm.npy"))
    bone = np.load(os.path.join(WD, f"{name}__bone.npy"))
    return img, pos, nrm, bone


def pad(img, covered, max_dist=12):
    """Fill uncovered texels with the nearest covered colour (texture edge padding)."""
    dist, (iy, ix) = ndi.distance_transform_edt(~covered, return_indices=True)
    out = img.copy()
    fill = (~covered) & (dist <= max_dist)
    out[fill] = img[iy[fill], ix[fill]]
    return out


meta = json.load(open(os.path.join(WD, "bones.json")))
bone_names = [b["name"] for b in meta["bones"]]
BIDX = {n: i for i, n in enumerate(bone_names)}
BPOS = {b["name"]: (np.array(b["head"]), np.array(b["tail"])) for b in meta["bones"]}


def is_bone(lbl, names):
    ids = [BIDX[n] for n in names if n in BIDX]
    return np.isin(lbl, ids)


# ====================================================================== body
img, pos, nrm, lbl = load(BODY)
H, W = lbl.shape
cov = lbl >= 0
L = lum(img)
h, s, v = hsv(img)
X, Y, Z = pos[..., 0], pos[..., 1], pos[..., 2]
out = img.copy()

purple = cov & (s > 0.10) & (h > 0.58) & (h < 0.9)
rope = cov & (s > 0.22) & (h > 0.04) & (h < 0.18)
hair = cov & is_bone(lbl, ["Head"]) & (L < 0.32) & ~purple & (Z > BPOS["Head"][0][2] + 0.12)

# the trunks are their own UV island: take the whole island, not just the purple-painted texels
islands, _ = ndi.label(cov)
comp, n = ndi.label(purple | rope)
sizes = ndi.sum(np.ones_like(L), comp, index=np.arange(1, n + 1))
main = comp == (1 + int(np.argmax(sizes)))
ids, counts = np.unique(islands[main], return_counts=True)
trunk_island = islands == ids[np.argmax(counts)]
trunk = (trunk_island | purple) & ~hair & ~(rope & ~trunk_island)
skin = cov & ~trunk & ~rope & ~hair

# --- skin everywhere first
out[skin] = grad(np.clip((L[skin] - 0.10) / 0.80, 0, 1), SKIN)

# --- trunks: crimson, normalised over the trunk region
tp = np.percentile(L[purple], [2, 98])
out[trunk] = grad(0.12 + 0.78 * np.clip((L[trunk] - tp[0]) / (tp[1] - tp[0]), 0, 1), CRIMSON)

# --- belt: a gold band at the rope's height across the trunks + the knot island
z_rope = float(np.median(Z[rope & trunk_island])) if (rope & trunk_island).any() else float(np.median(Z[rope]))
belt_half = 0.045
belt = trunk_island & (np.abs(Z - z_rope) < belt_half)
d = np.abs(Z[belt] - z_rope) / belt_half
shade = 0.62 + 0.25 * (1 - d ** 2)
out[belt] = grad(shade - 0.18 * (d > 0.82), GOLD)
knot = rope & ~trunk_island
out[knot] = grad(0.35 + 0.6 * np.clip((L[knot] - 0.15) / 0.6, 0, 1), GOLD)

# --- hem: everything within a band above the lowest trunk point at each angle around the leg,
# so the ragged teeth become a gold tassel fringe
xc0 = BPOS["Pelvis"][0][0]
legs = trunk_island & (Z < z_rope - 0.15)
li = np.nonzero(legs)
lx, ly, lz = X[li], Y[li], Z[li]
side = lx >= xc0
cx = np.where(side, BPOS["LLeg1"][0][0], BPOS["RLeg1"][0][0])
cy = np.where(side, BPOS["LLeg1"][0][1], BPOS["RLeg1"][0][1])
az = np.arctan2(ly - cy, lx - cx)
NB = 48
bins = np.clip(((az + np.pi) / (2 * np.pi) * NB).astype(int), 0, NB - 1) + NB * side.astype(int)
minz = np.full(2 * NB, np.inf)
np.minimum.at(minz, bins, lz)
local = lz - minz[bins]
HEM_H = 0.115
in_hem = local < HEM_H
tassel = (((az + np.pi) / (2 * np.pi) * 64) % 1.0) < 0.28
hem_shade = 0.44 + 0.4 * np.clip((L[li] - tp[0]) / (tp[1] - tp[0]), 0, 1) - 0.15 * tassel
hem = np.zeros_like(cov)
hem[li[0][in_hem], li[1][in_hem]] = True
out[li[0][in_hem], li[1][in_hem]] = grad(hem_shade[in_hem], GOLD)
edge = (local >= HEM_H) & (local < HEM_H + 0.016)
out[li[0][edge], li[1][edge]] *= 0.5
# the other trunk pieces (underside of the leg openings) get the trim colour too
other_trunk = purple & ~trunk_island
out[other_trunk] = grad(0.35 + 0.45 * np.clip((L[other_trunk] - tp[0]) / (tp[1] - tp[0]), 0, 1), GOLD)

# --- mane tuft (body texture): orange-gold, lighter towards the tips
if hair.any():
    hp = np.percentile(L[hair], [2, 98])
    zt = (Z[hair] - Z[hair].min()) / max(1e-6, np.ptp(Z[hair]))
    tl = np.clip((L[hair] - hp[0]) / max(1e-6, hp[1] - hp[0]), 0, 1)
    ang = np.arctan2(Y[hair] - np.nanmean(Y[hair]), X[hair] - np.nanmean(X[hair]))
    strands = 0.5 + 0.5 * np.sin(ang * 26 + Z[hair] * 30)
    out[hair] = grad(0.15 + 0.44 * tl + 0.32 * zt + 0.04 * strands, MANE)

# --- boots: feet plus shin below the boot top
ankle_z = BPOS["LLegAnkle"][0][2]
knee_z = BPOS["LLeg2"][0][2]
boot_top = ankle_z + 0.72 * (knee_z - ankle_z)
feet = cov & (is_bone(lbl, ["LLegAnkle", "LLegDigit11", "RLegAnkle", "RLegDigit11"]) |
              (is_bone(lbl, ["LLeg2", "RLeg2"]) & (Z < boot_top)))
# smooth the painted toe/foot detail away (normalised blur inside the boot region only)
fm = feet.astype(np.float32)
Lb = ndi.gaussian_filter(L * fm, 5) / np.maximum(ndi.gaussian_filter(fm, 5), 1e-4)
Lboot = 0.35 * L + 0.65 * Lb
out[feet] = grad(0.15 + 0.7 * np.clip((Lboot[feet] - 0.15) / 0.75, 0, 1), CRIMSON)
sole = feet & (nrm[..., 2] < -0.55) & (Z < ankle_z)
out[sole] = grad(0.55 + 0.4 * np.clip((Lboot[sole] - 0.2) / 0.7, 0, 1), TAPE)
cuff = feet & (Z > boot_top - 0.04)
out[cuff] = grad(0.55 + 0.35 * np.clip((L[cuff] - 0.2) / 0.7, 0, 1), GOLD)
cuff_line = feet & (Z > boot_top - 0.05) & (Z <= boot_top - 0.04)
out[cuff_line] *= 0.5
# gold toe cap
toe = feet & is_bone(lbl, ["LLegDigit11", "RLegDigit11"]) & ~sole
toe_edge = toe & ~ndi.binary_erosion(toe, iterations=3)
out[toe] = grad(0.5 + 0.4 * np.clip((Lboot[toe] - 0.2) / 0.7, 0, 1), GOLD)
out[toe_edge] *= 0.55

# --- wrist tape and gold armlets (UVs are mirrored, so each texel uses its own side's bones)
def limb_t(side, a, b):
    p0, p1 = BPOS[f"{side}{a}"][0], BPOS[f"{side}{b}"][0]
    ax = p1 - p0
    ln = np.linalg.norm(ax)
    ax = ax / ln
    return ((pos - p1) @ ax), ax, p1, ln


for side in ("L", "R"):
    forearm = cov & is_bone(lbl, [f"{side}Arm21", f"{side}Arm22", f"{side}ArmPalm"])
    t, ax, wrist, ln = limb_t(side, "Arm21", "ArmPalm")
    tape = forearm & (t > -0.36 * ln) & (t < 0.03)
    # angle around the forearm for a spiral wrap pattern
    e1 = np.cross(ax, [0, 0, 1.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    rel = pos - wrist
    ang = np.arctan2(rel @ e2, rel @ e1) / (2 * np.pi)
    wrap = (((t / 0.028) + ang) % 1.0) < 0.14
    base = grad(0.45 + 0.5 * np.clip((L - 0.2) / 0.7, 0, 1), TAPE)
    out[tape] = base[tape] * np.where(wrap[tape], 0.82, 1.0)[:, None]
    edge = tape & ((t < -0.36 * ln + 0.012) | (t > 0.03 - 0.008))
    out[edge] *= 0.7

    upper = cov & is_bone(lbl, [f"{side}Arm1"])
    tu, axu, elbow, lnu = limb_t(side, "Arm1", "Arm21")
    frac = 1 + tu / lnu  # 0 at shoulder, 1 at elbow
    armlet = upper & (frac > 0.52) & (frac < 0.66)
    fa = (frac[armlet] - 0.59) / 0.07
    out[armlet] = grad(0.62 + 0.25 * (1 - fa ** 2) - 0.2 * (np.abs(fa) > 0.78), GOLD)

# --- belt buckle emblem in the free square
BX, BY, BS = 912, 266, 104


def draw_buckle(size):
    k = 4
    S = size * k
    im = Image.new("RGB", (S, S), (0, 0, 0))
    d = ImageDraw.Draw(im)
    c = S / 2
    # radial gold plate
    yy_, xx_ = np.mgrid[0:S, 0:S]
    r = np.sqrt((xx_ - c) ** 2 + (yy_ - c) ** 2) / (S / 2)
    plate = grad(0.82 - 0.35 * r, GOLD)
    im = Image.fromarray((np.clip(plate, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    # sunburst rays
    for i in range(24):
        a0 = (i + 0.0) / 24 * 2 * np.pi
        a1 = (i + 0.5) / 24 * 2 * np.pi
        pts = [(c, c), (c + np.cos(a0) * S * 0.47, c + np.sin(a0) * S * 0.47),
               (c + np.cos(a1) * S * 0.47, c + np.sin(a1) * S * 0.47)]
        d.polygon(pts, fill=tuple(int(x * 255) for x in hexrgb("#B5781A")))
    # rims
    for rr, col, w in ((0.485, "#5E3A08", 6 * k), (0.44, "#FFE89A", 2 * k)):
        d.ellipse([c - S * rr, c - S * rr, c + S * rr, c + S * rr], outline=tuple(int(x * 255) for x in hexrgb(col)), width=w)
    # mane ring of scallops
    for i in range(14):
        a = i / 14 * 2 * np.pi
        px, py = c + np.cos(a) * S * 0.25, c + np.sin(a) * S * 0.25
        rr = S * 0.075
        d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=tuple(int(x * 255) for x in hexrgb("#E07A1C")),
                  outline=tuple(int(x * 255) for x in hexrgb("#6E2A04")), width=k * 2)
    # red gem
    rr = S * 0.19
    d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=tuple(int(x * 255) for x in hexrgb("#9E0F26")),
              outline=tuple(int(x * 255) for x in hexrgb("#3D0410")), width=k * 3)
    rr2 = S * 0.07
    d.ellipse([c - rr * 0.55 - rr2, c - rr * 0.55 - rr2, c - rr * 0.55 + rr2, c - rr * 0.55 + rr2],
              fill=tuple(int(x * 255) for x in hexrgb("#FF9AA8")))
    return im.resize((size, size), Image.LANCZOS)


buckle = np.asarray(draw_buckle(BS)).astype(np.float32) / 255
out[BY:BY + BS, BX:BX + BS] = buckle
covered_body = cov.copy()
covered_body[BY:BY + BS, BX:BX + BS] = True
out = pad(out, covered_body)
Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)).save(os.path.join(WD, "el_rugido_body.png"))

# ====================================================================== head (8 expression tiles)
himg, hpos, hnrm, hlbl = load(HEAD)
T = 256
cov0 = hlbl[:T, :T] >= 0
neck0 = hlbl[:T, :T] == BIDX["Neck"]
L0 = lum(himg[:T, :T])
dark0 = cov0 & (L0 < 0.22)
cl, n = ndi.label(dark0)
sizes = ndi.sum(np.ones_like(L0), cl, index=np.arange(1, n + 1))
hair0 = cl == (1 + int(np.argmax(sizes)))
hair0 = ndi.binary_closing(hair0, iterations=2) & cov0

ty, tx = np.mgrid[0:T, 0:T].astype(np.float32)
eye_c, eye_r = (217.0, 106.0), (22.0, 14.0)
e = ((tx - eye_c[0]) / eye_r[0]) ** 2 + ((ty - eye_c[1]) / eye_r[1]) ** 2
eye_open = e <= 1.0
mouth_c, mouth_r = (256.0, 163.0), (58.0, 31.0)
m = ((tx - mouth_c[0]) / mouth_r[0]) ** 2 + ((ty - mouth_c[1]) / mouth_r[1]) ** 2
mouth_hole = m <= 1.0
mask0 = cov0 & ~hair0 & ~eye_open & ~mouth_hole & ~neck0

trim = np.zeros_like(cov0)
trim |= (e > 1.0) & (e <= 1.5)                       # ring around the eye opening
flare = Image.new("L", (T, T), 0)
ImageDraw.Draw(flare).polygon([(197, 97), (200, 113), (163, 82), (172, 80)], fill=255)
trim |= np.asarray(flare) > 0                         # flare sweeping back to the temple
trim |= (m > 1.0) & (m <= 1.28)                       # ring around the mouth opening
hair_y = np.where(hair0.any(axis=0), np.argmax(hair0[::-1], axis=0), 0)
center = (tx >= 246) & (ty < 126)
trim |= center
trim |= (np.abs(tx - 256) / 13 + np.abs(ty - 76) / 13) <= 1.0  # forehead diamond
trim &= mask0
trim_dark = ndi.binary_dilation(trim, iterations=1) & mask0 & ~trim  # thin dark outline

hout = himg.copy()
for j in range(2):
    for i in range(4):
        ys_, xs_ = slice(j * T, (j + 1) * T), slice(i * T, (i + 1) * T)
        tile = himg[ys_, xs_]
        Lt = lum(tile)
        new = tile.copy()
        # lines (brows, wrinkles) = pixels much darker than their surroundings
        blur = ndi.uniform_filter(Lt, size=7)
        lines = np.clip((blur - Lt - 0.035) * 7.0, 0, 1)
        # skin / eyes / teeth inside the openings and on the neck
        open_ = cov0 & (eye_open | mouth_hole | neck0) & ~hair0
        R, G, B = tile[..., 0], tile[..., 1], tile[..., 2]
        iris = open_ & ((G - R) > 0.08) & ((G - B) > -0.06)
        white = open_ & (Lt > 0.80) & ~iris
        skinish = open_ & ~iris & ~white
        new[skinish] = grad(np.clip((Lt[skinish] - 0.10) / 0.80, 0, 1), SKIN)
        new[white] = np.clip(tile[white] * np.array([1.0, 0.98, 0.93]), 0, 1)
        new[iris] = grad(np.clip((Lt[iris] - 0.08) / 0.6, 0, 1), AMBER)
        # mask
        new[mask0] = grad(0.10 + 0.85 * np.clip((Lt[mask0] - 0.12) / 0.70, 0, 1), CRIMSON)
        new[trim] = grad(0.40 + 0.5 * np.clip((Lt[trim] - 0.12) / 0.70, 0, 1), GOLD)
        new[trim_dark] *= 0.45
        # keep the expression linework (brows etc.) on top of the mask
        lm = mask0 | trim
        new[lm] *= (1 - 0.85 * lines[lm])[:, None]
        # mane: darker at the roots (near the mask), lighter at the outer edge, with strands
        if hair0.any():
            hp = np.percentile(Lt[hair0], [2, 98])
            tl = np.clip((Lt[hair0] - hp[0]) / max(1e-6, hp[1] - hp[0]), 0, 1)
            root = np.clip(ndi.distance_transform_edt(hair0)[hair0] / 18.0, 0, 1)
            strands = 0.5 + 0.5 * np.sin(tx[hair0] * 0.55 + ty[hair0] * 0.9 + 3 * np.sin(ty[hair0] * 0.07)
                                         + 2.5 * np.sin(tx[hair0] * 0.13))
            new[hair0] = grad(0.14 + 0.48 * tl + 0.3 * (1 - root * 0.6) + 0.03 * strands, MANE)
        new = pad(new, cov0, max_dist=24)
        hout[ys_, xs_] = new

Image.fromarray((np.clip(hout, 0, 1) * 255 + 0.5).astype(np.uint8)).save(os.path.join(WD, "el_rugido_head.png"))
json.dump({"belt_z": z_rope, "boot_top": float(boot_top), "buckle_square_px": [BX, BY, BS], "body_size": [W, H]},
          open(os.path.join(WD, "el_rugido_meta.json"), "w"), indent=1)
print("belt z", round(z_rope, 3), "boot top", round(float(boot_top), 3),
      "| trunks", int(purple.sum()), "hem", int(hem.sum()), "hair(body)", int(hair.sum()),
      "feet", int(feet.sum()), "| head mask px", int(mask0.sum()), "hair", int(hair0.sum()))
