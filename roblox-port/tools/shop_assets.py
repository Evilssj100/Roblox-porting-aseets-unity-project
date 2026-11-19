"""Store and hub-menu images -> roblox-port/assets/shop/<key>.png (uploaded as images, keys gui_...):

* original GUI art from the archive's shopping, HUD and goodies bundles (extracted with UnityPy into <gui_extract>),
  only pieces without logos, agency badges or licensed characters (checked on contact sheets): item tags and
  ribbons, buy buttons, the gold display, tab titles, the global-nav bar, its icons and drop-down buttons, the
  gold and fractal icons, the potion icons
* original icons drawn here where the archive has none or the original showed a licensed character: silver and
  gold badges, the title scroll, the medallion, the sidekick paw, the gold, ghost and invisibility potions, and a
  hero card per port hero (no renders of the heroes: two of the repurposed looks still need their redesign)

Usage: python shop_assets.py <gui_extract dir> <roblox-port dir>
"""
import math
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFilter

SHOP = ["L_button_buygold_shoppingpopup_normal", "L_button_buygold_shoppingpopup_highlight",
        "L_button_buygold_shoppingpopup_pressed", "L_coming_soon_burst", "L_new_label",
        "L_shopping_adspace_nobutton_normal", "L_shopping_adspace_nobutton_highlight",
        "L_shopping_adspace_nobutton_pressed", "L_shopping_buybutton_gold_normal", "L_shopping_buybutton_gold_highlight",
        "L_shopping_buybutton_gold_pressed", "L_shopping_buybutton_silver_normal", "L_shopping_buybutton_silver_highlight",
        "L_shopping_buybutton_silver_pressed", "L_shopping_gold_display", "L_shopping_item_limited_overlay",
        "L_shopping_item_oneday_overlay", "L_shopping_item_oneweek_overlay", "L_shopping_item_sale_overlay",
        "L_shopping_item_twoweeks_overlay", "L_shopping_itemoftheday_title", "L_shopping_owned_indicator",
        "L_shopping_slideview_buy_normal", "L_shopping_slideview_buy_highlight", "L_shopping_slideview_buy_pressed",
        "L_shopping_ticket", "L_tabtitle_badges", "L_tabtitle_cards", "L_tabtitle_goodies", "L_tabtitle_heroes",
        "L_tabtitle_hq", "L_tabtitle_missions", "L_tabtitle_more", "L_tabtitle_sidekicks", "L_tabtitle_special",
        "tag_earlyaccess", "tag_featured", "tag_new", "tag_oneday", "tag_oneweek", "tag_owned", "tag_sale"]
HUD = ["globalnav_bg", "globalnav2_bg", "globalnav_store", "globalnav_mission", "globalnav_explore",
       "globalnav_achievements", "globalnav_craft", "globalnav_cards", "globalnav_inventory", "globalnav_arcade",
       "globalnav_friends", "globalnav_settings", "globalnav_hq", "globalnav_toggle_on_normal",
       "globalnav_toggle_on_highlight", "globalnav_toggle_off_normal", "globalnav_toggle_off_highlight",
       "button_drop_down_normal", "button_drop_down_highlight", "button_drop_down_pressed",
       "button_drop_down_on_normal", "button_drop_down_on_highlight", "button_drop_down_on_pressed",
       "gold_icon", "fractal_icon", "globalnav_underlay3_normal", "globalnav_underlay3c_normal",
       "globalnav_underlay3c_highlight", "globalnav_underlay3l_normal", "globalnav_underlay3l_highlight"]
# the zone HUD and the daily panels (gameworld bundles) and common icons: generic pieces only
WORLD = ["daily_reward_gold_1", "daily_reward_gold_2", "daily_reward_gold_3", "daily_reward_silver_1",
         "daily_reward_silver_2", "daily_reward_silver_3", "daily_reward_tickets_1", "daily_reward_tickets_2",
         "daily_reward_tickets_3", "daily_reward_tickets_4", "dailyreward_panel_collected_background",
         "dailyreward_panel_today", "dailyreward_panel_today_fx1", "dailyreward_panel_today_fx2",
         "dailyreward_panel_unclaimed", "mshs_gameworld_HUD_changehero_normal", "mshs_gameworld_HUD_changehero_highlight",
         "mshs_gameworld_HUD_changehero_pressed", "mshs_gameworld_HUD_level_background", "mshs_gameworld_HUD_playerframe",
         "mshs_gameworld_HUD_shop_normal", "mshs_gameworld_HUD_shop_highlight", "mshs_gameworld_HUD_shop_pressed"]
EN_WORLD = ["L_dailyreward_label_day1", "L_dailyreward_label_day2", "L_dailyreward_label_day3", "L_dailyreward_label_day4",
            "L_dailyreward_label_day5", "L_dailyreward_label_day6", "L_dailyreward_label_day7", "L_dailyreward_label_day8",
            "L_dailyreward_label_today", "L_dailyreward_mainpanel", "L_game_world_xp_gain_icon",
            "L_gameworld_portrait_text", "L_ok_normal", "L_ok_highlight", "L_ok_pressed"]
COMMON = ["fractal", "golden_fractal", "button_close_normal", "button_close_highlight", "button_close_pressed",
          "mshs_common_hud_character_frame", "mshs_levelup_star"]


def world_key(prefix, name):
    n = name[2:] if name.startswith("L_") else name
    n = n.replace("mshs_gameworld_HUD_", "hud_").replace("mshs_common_hud_", "").replace("mshs_", "")
    return prefix + n


# potion icons kept as they are (generic objects); gold, ghost, invisibility, shadow, void, growth and shrink are
# drawn below (the shadow, void, growth and shrink originals show licensed characters or their silhouettes)
POTIONS = ["fart", "electricityball", "seasonal", "snow", "stinkbomb", "alien", "green",
           "damageboost", "speedboost", "armorboost", "xpboost", "healthboost", "rude", "dance", "1000xp", "5000xp",
           "fractal"]


def outline(im, width=6, color=(30, 24, 40, 255)):
    """a dark cartoon outline around an RGBA drawing"""
    a = im.split()[3]
    grown = a.filter(ImageFilter.MaxFilter(width * 2 + 1))
    base = Image.new("RGBA", im.size, color)
    base.putalpha(grown)
    base.alpha_composite(im)
    return base


def star_pts(cx, cy, r_out, r_in, n=5, rot=-math.pi / 2):
    return [(cx + math.cos(rot + k * math.pi / n) * (r_out if k % 2 == 0 else r_in),
             cy + math.sin(rot + k * math.pi / n) * (r_out if k % 2 == 0 else r_in)) for k in range(n * 2)]


def badge(metal):
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    light, dark = ((236, 238, 244), (140, 150, 168)) if metal == "silver" else ((255, 220, 90), (196, 128, 20))
    shield = [(128, 22), (222, 52), (210, 150), (128, 236), (46, 150), (34, 52)]
    d.polygon(shield, fill=dark)
    inner = [(128, 40), (204, 64), (194, 146), (128, 214), (62, 146), (52, 64)]
    d.polygon(inner, fill=light)
    d.polygon(star_pts(128, 124, 62, 26), fill=dark)
    d.polygon(star_pts(128, 120, 54, 22), fill=(255, 255, 255) if metal == "silver" else (255, 246, 200))
    return outline(im)


def scroll():
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([40, 70, 216, 186], radius=18, fill=(250, 232, 180))
    for x in (40, 216):
        d.ellipse([x - 22, 60, x + 22, 196], fill=(222, 186, 110))
        d.ellipse([x - 10, 112, x + 10, 144], fill=(170, 120, 60))
    for k, y in enumerate((96, 120, 144, 166)):
        d.rounded_rectangle([72, y, 184 - (k % 2) * 30, y + 8], radius=4, fill=(150, 110, 70))
    d.polygon([(110, 186), (146, 186), (150, 232), (128, 216), (106, 232)], fill=(210, 50, 50))
    return outline(im)


def medallion():
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(84, 10), (122, 10), (140, 110), (102, 110)], fill=(60, 110, 220))
    d.polygon([(134, 10), (172, 10), (154, 110), (116, 110)], fill=(220, 60, 60))
    d.ellipse([48, 88, 208, 248], fill=(206, 144, 30))
    d.ellipse([62, 102, 194, 234], fill=(255, 214, 80))
    d.polygon(star_pts(128, 168, 50, 21), fill=(206, 144, 30))
    return outline(im)


def paw():
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([14, 14, 242, 242], fill=(120, 196, 255))
    d.ellipse([28, 28, 228, 228], fill=(70, 140, 225))
    d.ellipse([78, 120, 178, 206], fill=(255, 255, 255))
    for cx, cy in ((72, 100), (106, 70), (150, 70), (184, 100)):
        d.ellipse([cx - 20, cy - 24, cx + 20, cy + 24], fill=(255, 255, 255))
    return outline(im)


def flask(liquid, glass=(210, 240, 255, 150), sparkle=True, dashed=False, extra=None):
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([104, 30, 152, 92], fill=glass)
    d.ellipse([46, 76, 210, 240], fill=glass)
    d.chord([56, 86, 200, 230], 10, 170, fill=liquid)
    d.rectangle([98, 18, 158, 40], fill=(150, 100, 60, 255))
    if dashed:
        for k in range(16):
            a0 = k * 2 * math.pi / 16
            d.arc([40, 70, 216, 246], math.degrees(a0), math.degrees(a0) + 11, fill=(255, 255, 255, 255), width=6)
    if sparkle:
        for cx, cy, r in ((90, 140, 16), (170, 120, 12), (140, 190, 10)):
            d.polygon(star_pts(cx, cy, r, r * 0.35, n=4), fill=(255, 255, 255, 255))
    if extra:
        extra(d)
    d.ellipse([74, 104, 100, 150], fill=(255, 255, 255, 120))
    return outline(im)


# symbols for the potions whose original icons showed licensed characters (drawn on the flask)
def moon(d):
    d.ellipse([92, 122, 164, 194], fill=(250, 246, 255, 255))
    d.ellipse([110, 112, 182, 184], fill=(70, 40, 110, 255))


def starfield(d):
    for cx, cy, r in ((96, 150, 14), (150, 128, 10), (164, 182, 15), (118, 200, 9), (130, 166, 6)):
        d.polygon(star_pts(cx, cy, r, r * 0.35, n=4), fill=(220, 200, 255, 255))
    d.arc([70, 110, 186, 226], 200, 340, fill=(150, 90, 230, 255), width=6)


def arrow(up):
    tip, head, base = (104, 150, 206) if up else (214, 168, 112)

    def draw(d):
        d.polygon([(128, tip), (170, head), (146, head), (146, base), (110, base), (110, head), (86, head)],
                  fill=(255, 255, 255, 255))
    return draw


def ghost():
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([54, 28, 202, 176], fill=(235, 245, 255, 255))
    d.rectangle([54, 100, 202, 210], fill=(235, 245, 255, 255))
    for k in range(4):  # wavy hem
        x = 54 + k * 37
        d.ellipse([x, 190, x + 37, 236], fill=(235, 245, 255, 255) if k % 2 == 0 else (0, 0, 0, 0))
    d.ellipse([96, 90, 120, 126], fill=(40, 40, 70, 255))
    d.ellipse([140, 90, 164, 126], fill=(40, 40, 70, 255))
    d.ellipse([116, 140, 142, 166], fill=(40, 40, 70, 255))
    return outline(im)


def hero_card(color):
    """an original hero card: a caped figure on a coloured disc (the store shows the hero's name under it)"""
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    dark = tuple(int(c * 0.55) for c in color)
    d.ellipse([12, 12, 244, 244], fill=dark + (255,))
    d.ellipse([26, 26, 230, 230], fill=color + (255,))
    d.polygon([(92, 110), (164, 110), (196, 226), (60, 226)], fill=dark + (255,))  # cape
    d.ellipse([100, 52, 156, 108], fill=(255, 255, 255, 255))  # head
    d.polygon([(96, 112), (160, 112), (172, 200), (84, 200)], fill=(255, 255, 255, 255))  # body
    d.polygon(star_pts(128, 148, 26, 11), fill=color + (255,))  # chest star
    return outline(im)


HERO_COLORS = {"ElRugido": (226, 70, 50), "Skyvolt": (40, 170, 150), "Aurora": (120, 90, 220),
               "Magmaul": (230, 130, 40), "NightGecko": (60, 170, 80)}


def main():
    src, port = sys.argv[1:3]
    out = os.path.join(port, "assets", "shop")
    os.makedirs(out, exist_ok=True)

    def put(im_path, key):
        im = Image.open(im_path).convert("RGBA")
        if max(im.size) > 512:
            im.thumbnail((512, 512), Image.LANCZOS)
        im.save(os.path.join(out, key + ".png"))

    for n in SHOP:
        put(os.path.join(src, "en_us_shopping_bundle", n + ".png"), "gui_shop_" + n.replace("L_", "").replace("shopping_", ""))
    for n in HUD:
        put(os.path.join(src, "hud_bundle", n + ".png"), "gui_hud_" + n)
    for n in POTIONS:
        put(os.path.join(src, "goodieseffects_bundle", f"goody_effects_{n}_shopping.png"), "gui_potion_" + n)
    for n in WORLD:
        put(os.path.join(src, "gameworld_bundle", n + ".png"), world_key("gui_world_", n))
    for n in EN_WORLD:
        put(os.path.join(src, "en_us_gameworld_bundle", n + ".png"), world_key("gui_world_", n))
    for n in COMMON:
        put(os.path.join(src, "common_bundle", n + ".png"), world_key("gui_common_", n))
    drawn = {"gui_shop_badge_silver": badge("silver"), "gui_shop_badge_gold": badge("gold"),
             "gui_shop_title": scroll(), "gui_shop_medallion": medallion(), "gui_shop_sidekick": paw(),
             "gui_potion_gold": flask((236, 186, 40, 255)), "gui_potion_ghost": ghost(),
             "gui_potion_invisible": flask((200, 230, 255, 90), sparkle=False, dashed=True),
             "gui_potion_shadow": flask((70, 40, 110, 255), sparkle=False, extra=moon),
             "gui_potion_void": flask((20, 16, 30, 255), sparkle=False, extra=starfield),
             "gui_potion_growth": flask((90, 200, 80, 255), sparkle=False, extra=arrow(True)),
             "gui_potion_shrink": flask((80, 150, 230, 255), sparkle=False, extra=arrow(False)),
             **{f"gui_hero_{h}": hero_card(c) for h, c in HERO_COLORS.items()}}
    for k, im in drawn.items():
        im.save(os.path.join(out, k + ".png"))
    print(f"{len(os.listdir(out))} images in {out}")


if __name__ == "__main__":
    main()
