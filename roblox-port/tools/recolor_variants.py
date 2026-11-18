"""Costume recolors of a hero's textures for enemy variants (crimson costume hue-shifted; skin, mane and
tape untouched; gold trims optionally turned silver). Same rule as the old in-game EditableImage recolor,
done offline so the variants are plain image assets (no runtime memory budget).

Usage: python recolor_variants.py <out_dir> <Hero> <texture.png>...
Writes <out_dir>/<Hero>_<Variant>_<texture name>.png for every variant in VARIANTS.
"""
import os
import sys

import numpy as np
from PIL import Image

VARIANTS = [  # keep in sync with GameConfig.Variants
    {"name": "Azul", "hue": 0.60, "sat": 1.0, "val": 1.0, "gold": "silver"},
    {"name": "Verde", "hue": 0.36, "sat": 0.9, "val": 0.95, "gold": "gold"},
    {"name": "Morado", "hue": 0.78, "sat": 0.9, "val": 1.0, "gold": "gold"},
    {"name": "Negro", "hue": 0.0, "sat": 0.0, "val": 0.42, "gold": "silver"},
]


def rgb2hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    safe = np.where(d > 0, d, 1)
    h = np.where(mx == r, ((g - b) / safe) % 6, np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4)) / 6
    s = np.where(mx > 0, d / np.where(mx > 0, mx, 1), 0)
    return h, s, mx, d


def hsv2rgb(h, s, v):
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    conds = [i == k for k in range(6)]
    return np.stack([np.select(conds, [v, q, p, p, t, v]), np.select(conds, [t, v, v, q, p, p]),
                     np.select(conds, [p, p, t, v, v, q])], -1)


def recolor(rgb, var):
    h, s, v, d = rgb2hsv(rgb)
    colored = (v > 0.06) & (d > 0.42 * v)
    crimson = colored & ((h > 0.93) | (h < 0.025))
    gold = colored & (h > 0.09) & (h < 0.17) & (s > 0.45) if var["gold"] == "silver" else np.zeros_like(colored)
    out = rgb.copy()
    nh = np.full_like(h, var["hue"])
    out[crimson] = hsv2rgb(nh, np.clip(s * var["sat"], 0, 1), np.clip(v * var["val"], 0, 1))[crimson]
    out[gold] = hsv2rgb(np.full_like(h, 0.58), s * 0.12, np.clip(v * 1.05, 0, 1))[gold]
    return out


if __name__ == "__main__":
    out_dir, hero, textures = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out_dir, exist_ok=True)
    for tex in textures:
        rgb = np.asarray(Image.open(tex).convert("RGB"), np.float64) / 255
        base = os.path.splitext(os.path.basename(tex))[0].replace(hero + "_", "")
        for var in VARIANTS:
            img = Image.fromarray((recolor(rgb, var) * 255 + 0.5).astype(np.uint8))
            p = os.path.join(out_dir, f"{hero}_{var['name']}_{base}.png")
            img.save(p)
            print(p)
