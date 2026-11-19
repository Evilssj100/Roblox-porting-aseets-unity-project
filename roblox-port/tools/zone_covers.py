"""Original replacement images for licensed artwork in the social zones (used with port_zone.py --retexture):

* plaza_pizza_windows.png: the pizza shop's window atlas with its sign panel (a licensed character) repainted as
  an original sign: a checkered band, a pepperoni slice and the word PIZZA
* plaza_street_sign.png: a plain green street sign with a generic name (the original named a licensed location)
* villain_*.png: the villain zone's posters and billboard (the originals showed a licensed character): an original
  warning poster, a crown-and-skyline crest, the zone's own lettering and an evening skyline

Usage: python zone_covers.py <original windows_pizza_atl.png> <out_dir>
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def font(size):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def pizza_panel(w, h):
    im = Image.new("RGB", (w, h), (238, 232, 214))
    d = ImageDraw.Draw(im)
    band_top, cell = int(h * 0.58), max(8, w // 16)
    for row in range(2):  # checkered band
        for col in range(w // cell + 1):
            c = (196, 48, 36) if (row + col) % 2 == 0 else (250, 246, 236)
            y0 = band_top + row * cell
            d.rectangle([col * cell, y0, col * cell + cell - 1, y0 + cell - 1], fill=c)
    d.rectangle([0, band_top - 4, w, band_top - 1], fill=(60, 120, 60))
    d.rectangle([0, band_top + 2 * cell, w, band_top + 2 * cell + 3], fill=(60, 120, 60))
    # a slice: crust arc on top, point down
    cx, top, r = w // 2, int(h * 0.30), int(w * 0.30)
    tip = (cx, int(h * 0.92))
    left, right = (cx - r, top), (cx + r, top)
    d.polygon([left, right, tip], fill=(250, 200, 70), outline=(150, 90, 30))
    d.rounded_rectangle([cx - r - 6, top - 12, cx + r + 6, top + 6], radius=9, fill=(205, 140, 60), outline=(150, 90, 30))
    for fx, fy in ((-0.35, 0.22), (0.3, 0.3), (-0.05, 0.5), (0.12, 0.72), (-0.2, 0.45)):
        px = cx + int(fx * r * 1.6 * (1 - fy * 0.8))
        py = top + int(fy * (tip[1] - top))
        d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=(190, 45, 35))
    f = font(int(h * 0.2))
    text = "PIZZA"
    tw = d.textlength(text, font=f)
    for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
        d.text((cx - tw / 2 + ox, int(h * 0.04) + oy), text, font=f, fill=(40, 30, 20))
    d.text((cx - tw / 2, int(h * 0.04)), text, font=f, fill=(255, 214, 60))
    return im


def street_sign(w=256, h=128, text="MAPLE ST"):
    im = Image.new("RGB", (w, h), (34, 102, 52))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([5, 5, w - 6, h - 6], radius=10, outline=(240, 240, 230), width=4)
    size = int(h * 0.42)
    f = font(size)
    while d.textlength(text, font=f) > w - 30 and size > 8:  # fit inside the border
        size -= 2
        f = font(size)
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, (h - size) / 2 - 4), text, font=f, fill=(245, 245, 235))
    return im


def outlined(d, xy, text, f, fill, outline=(30, 24, 18), w=4):
    x, y = xy
    for ox in range(-w, w + 1, 2):
        for oy in range(-w, w + 1, 2):
            d.text((x + ox, y + oy), text, font=f, fill=outline)
    d.text((x, y), text, font=f, fill=fill)


def fit_font(d, text, max_w, size):
    f = font(size)
    while d.textlength(text, font=f) > max_w and size > 8:
        size -= 4
        f = font(size)
    return f, size


def skyline(d, w, h, base, color, seed=3):
    import random
    rnd = random.Random(seed)
    x = 0
    while x < w:
        bw, bh = rnd.randint(w // 20, w // 8), rnd.randint(h // 6, h // 2)
        d.rectangle([x, base - bh, x + bw, base], fill=color)
        if rnd.random() < 0.4:  # a chimney or antenna
            d.rectangle([x + bw // 3, base - bh - h // 14, x + bw // 3 + max(3, bw // 8), base - bh], fill=color)
        x += bw + rnd.randint(0, w // 60)


def villain_watch_poster(n=1024):
    """the 'watching' poster: an original warning poster (a robotic eye and a slogan)"""
    im = Image.new("RGB", (n, n), (232, 196, 64))
    d = ImageDraw.Draw(im)
    d.rectangle([0, int(n * 0.55), n, n], fill=(28, 40, 74))
    cx, cy, r = n // 2, int(n * 0.32), int(n * 0.2)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(48, 52, 60), outline=(20, 20, 24), width=14)
    d.ellipse([cx - r * 0.6, cy - r * 0.6, cx + r * 0.6, cy + r * 0.6], fill=(200, 40, 36))
    d.ellipse([cx - r * 0.22, cy - r * 0.22, cx + r * 0.22, cy + r * 0.22], fill=(255, 230, 120))
    for k in range(8):  # bolts around the lens
        a = k * math.pi / 4
        bx, by = cx + math.cos(a) * r * 0.82, cy + math.sin(a) * r * 0.82
        d.ellipse([bx - 12, by - 12, bx + 12, by + 12], fill=(150, 150, 160))
    f, size = fit_font(d, "BEHAVE!", n * 0.86, int(n * 0.2))
    outlined(d, ((n - d.textlength("BEHAVE!", font=f)) / 2, n * 0.6), "BEHAVE!", f, (250, 240, 220), w=6)
    f2, _ = fit_font(d, "the management is watching", n * 0.8, int(n * 0.06))
    d.text(((n - d.textlength("the management is watching", font=f2)) / 2, n * 0.86), "the management is watching", font=f2,
           fill=(232, 196, 64))
    return im


def villain_boss_poster(n=1024):
    """the billboard poster: an original crest (a crown over a skyline)"""
    im = Image.new("RGB", (n, n), (236, 214, 160))
    d = ImageDraw.Draw(im)
    skyline(d, n, n, int(n * 0.8), (60, 70, 58), seed=7)
    d.rectangle([0, int(n * 0.8), n, n], fill=(60, 70, 58))
    cx, top, w, h = n // 2, int(n * 0.14), int(n * 0.5), int(n * 0.28)
    pts = [(cx - w // 2, top + h), (cx - w // 2, top + h // 3), (cx - w // 4, top + h * 0.6), (cx, top),
           (cx + w // 4, top + h * 0.6), (cx + w // 2, top + h // 3), (cx + w // 2, top + h)]
    d.polygon(pts, fill=(214, 168, 40), outline=(90, 62, 10))
    d.rectangle([cx - w // 2, top + h, cx + w // 2, top + h + h // 4], fill=(190, 140, 30), outline=(90, 62, 10))
    for k in (-1, 0, 1):
        gx = cx + k * w // 4
        d.ellipse([gx - 18, top + h + 8, gx + 18, top + h + 44], fill=(160, 30, 40))
    f, _ = fit_font(d, "VILLAIN TOWN", n * 0.9, int(n * 0.13))
    outlined(d, ((n - d.textlength("VILLAIN TOWN", font=f)) / 2, n * 0.83), "VILLAIN TOWN", f, (240, 200, 60), w=5)
    return im


def villain_letters(w=1024, h=512):
    im = Image.new("RGB", (w, h), (48, 48, 52))
    d = ImageDraw.Draw(im)
    f, size = fit_font(d, "VILLAIN TOWN", w * 0.92, int(h * 0.3))
    outlined(d, ((w - d.textlength("VILLAIN TOWN", font=f)) / 2, (h - size) / 2 - 10), "VILLAIN TOWN", f, (236, 190, 70), w=6)
    return im


def villain_skyline(w=1024, h=512):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):  # yellow evening sky
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(250 - 40 * t), int(236 - 90 * t), int(150 - 100 * t)))
    d.ellipse([w * 0.72, h * 0.12, w * 0.72 + h * 0.22, h * 0.34], fill=(255, 250, 220))
    skyline(d, w, h, int(h * 0.92), (70, 66, 60), seed=11)
    d.rectangle([0, int(h * 0.92), w, h], fill=(70, 66, 60))
    return im


def main():
    src, out = sys.argv[1:3]
    os.makedirs(out, exist_ok=True)
    atl = Image.open(src).convert("RGB")
    W, H = atl.size
    # the sign panel: left half of the band between 50% and ~72.7% of the height (512x1024: 0..256 x 512..744)
    box = (0, int(H * 0.5), W // 2, int(H * 0.7266))
    atl.paste(pizza_panel(box[2] - box[0], box[3] - box[1]), box[:2])
    atl.save(os.path.join(out, "plaza_pizza_windows.png"))
    street_sign().save(os.path.join(out, "plaza_street_sign.png"))
    villain_watch_poster().save(os.path.join(out, "villain_watch_poster.png"))
    villain_boss_poster().save(os.path.join(out, "villain_boss_poster.png"))
    villain_letters().save(os.path.join(out, "villain_letters.png"))
    villain_skyline().save(os.path.join(out, "villain_skyline.png"))
    print("wrote", os.listdir(out))


if __name__ == "__main__":
    main()
