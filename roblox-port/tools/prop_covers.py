"""Original replacement images for licensed or franchise artwork on the social-zone props (merge_props.py --retexture):

* launcher_mission.png / launcher_cards.png / launcher_hq.png: the game launcher signs (the originals showed
  characters and a franchise vehicle): a lightning badge, two playing cards with a star, a tower with a flag
* manhole.png: a plain manhole cover (the original read the franchise's city name)
* hangar_door_b.png: the hangar door with its licensed emblem painted out (panel colour)

Usage: python prop_covers.py <original Door_Hangar_B image> <out_dir>
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def glow(im, color, radius=10):
    """a soft halo around the drawn shape (the signs are self-lit on black)"""
    a = np.asarray(im.convert("L")).astype(float)
    halo = Image.fromarray((a > 10).astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(radius))
    base = Image.new("RGB", im.size, (0, 0, 0))
    base.paste(Image.new("RGB", im.size, color), (0, 0), halo.point(lambda v: int(v * 0.6)))
    base.paste(im, (0, 0), Image.fromarray((a > 10).astype(np.uint8) * 255))
    return base


def launcher_mission(n=256):
    im = Image.new("RGB", (n, n), (0, 0, 0))
    d = ImageDraw.Draw(im)
    c, r = n / 2, n * 0.4
    d.ellipse([c - r, c - r, c + r, c + r], fill=(240, 120, 30), outline=(255, 220, 120), width=8)
    bolt = [(0.56, 0.12), (0.3, 0.55), (0.48, 0.55), (0.4, 0.88), (0.72, 0.42), (0.53, 0.42), (0.62, 0.12)]
    d.polygon([(x * n, y * n) for x, y in bolt], fill=(255, 245, 200), outline=(120, 50, 10))
    return glow(im, (255, 140, 40))


def launcher_cards(n=256):
    im = Image.new("RGBA", (n, n), (0, 0, 0, 255))
    for ang, col, dx in ((-14, (120, 200, 255), -0.1), (10, (255, 225, 120), 0.1)):
        card = Image.new("RGBA", (int(n * 0.42), int(n * 0.6)), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=14, fill=col + (255,), outline=(40, 40, 60, 255), width=6)
        cx, cy, r = card.width / 2, card.height / 2, card.width * 0.28
        pts = [(cx + math.cos(-math.pi / 2 + k * math.pi / 5) * (r if k % 2 == 0 else r * 0.45),
                cy + math.sin(-math.pi / 2 + k * math.pi / 5) * (r if k % 2 == 0 else r * 0.45)) for k in range(10)]
        cd.polygon(pts, fill=(250, 250, 250, 255), outline=(40, 40, 60, 255))
        card = card.rotate(ang, expand=True, resample=Image.BICUBIC)
        im.alpha_composite(card, (int(n / 2 - card.width / 2 + dx * n), int(n / 2 - card.height / 2)))
    return glow(im.convert("RGB"), (120, 180, 255))


def launcher_hq(n=256):
    im = Image.new("RGB", (n, n), (0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([n * 0.3, n * 0.35, n * 0.7, n * 0.88], fill=(90, 170, 240), outline=(220, 240, 255), width=6)
    d.polygon([(n * 0.25, n * 0.37), (n * 0.5, n * 0.18), (n * 0.75, n * 0.37)], fill=(60, 110, 200), outline=(220, 240, 255))
    for row in range(3):
        for col in range(2):
            x, y = n * (0.37 + col * 0.15), n * (0.45 + row * 0.13)
            d.rectangle([x, y, x + n * 0.1, y + n * 0.08], fill=(255, 230, 120))
    d.line([(n * 0.5, n * 0.18), (n * 0.5, n * 0.04)], fill=(220, 240, 255), width=5)
    d.polygon([(n * 0.5, n * 0.04), (n * 0.66, n * 0.08), (n * 0.5, n * 0.12)], fill=(240, 80, 60))
    return glow(im, (90, 170, 240))


def manhole(n=512):
    im = Image.new("RGB", (n, n), (46, 48, 50))
    d = ImageDraw.Draw(im)
    c = n / 2
    for r, col in ((0.47, (70, 72, 74)), (0.43, (40, 42, 44)), (0.39, (78, 80, 82))):
        d.ellipse([c - r * n, c - r * n, c + r * n, c + r * n], fill=col)
    for k in range(-7, 8):  # a cross-hatch grip pattern
        off = k * n * 0.05
        d.line([(c + off - n * 0.3, c - n * 0.3), (c + off + n * 0.3, c + n * 0.3)], fill=(58, 60, 62), width=6)
        d.line([(c + off + n * 0.3, c - n * 0.3), (c + off - n * 0.3, c + n * 0.3)], fill=(58, 60, 62), width=6)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).ellipse([c - 0.39 * n, c - 0.39 * n, c + 0.39 * n, c + 0.39 * n], fill=255)
    rim = Image.new("RGB", (n, n), (70, 72, 74))
    ImageDraw.Draw(rim).ellipse([c - 0.47 * n, c - 0.47 * n, c + 0.47 * n, c + 0.47 * n], fill=(70, 72, 74))
    out = Image.new("RGB", (n, n), (46, 48, 50))
    out.paste(rim, (0, 0))
    out.paste(im, (0, 0), mask)
    d = ImageDraw.Draw(out)
    for k in range(6):  # bolts on the rim
        a = k * math.pi / 3
        x, y = c + math.cos(a) * 0.43 * n, c + math.sin(a) * 0.43 * n
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(30, 30, 32))
    return out


def paint_out_emblem(path):
    """the hangar door's licensed emblem (a disc on the blue lower panel) painted out: the panel becomes one colour"""
    im = np.asarray(Image.open(path).convert("RGB")).astype(int)
    H, W = im.shape[:2]
    y0 = int(H * 0.6)
    region = im[y0:, :].copy()
    blue = region[..., 2] > region[..., 0] + 25
    panel = np.median(region[blue], axis=0) if blue.any() else np.array([51, 59, 78])
    ys, xs = np.where(blue)
    if len(xs):
        x0, x1 = xs.min(), xs.max()
        light = region.min(axis=2) > 120
        inside = np.zeros_like(blue)
        for y in range(region.shape[0]):  # between the panel's left and right edge on each row
            row = np.where(blue[y])[0]
            if len(row) > 1:
                inside[y, row.min():row.max() + 1] = True
        region[(blue | (light & inside)) & inside | blue] = panel.astype(int)
    im[y0:, :] = region
    return Image.fromarray(im.astype(np.uint8))


def main():
    door, out = sys.argv[1:3]
    os.makedirs(out, exist_ok=True)
    launcher_mission().save(os.path.join(out, "launcher_mission.png"))
    launcher_cards().save(os.path.join(out, "launcher_cards.png"))
    launcher_hq().save(os.path.join(out, "launcher_hq.png"))
    manhole().save(os.path.join(out, "manhole.png"))
    paint_out_emblem(door).save(os.path.join(out, "hangar_door_b.png"))
    print("wrote", sorted(os.listdir(out)))


if __name__ == "__main__":
    main()
