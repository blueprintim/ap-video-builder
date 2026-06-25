"""
render_slides.py — generates opening slide, closing slide, and thumbnail
for a crane listing, in three aspect ratios (16:9, 9:16, 1:1).

Layouts are computed per-ratio rather than scaled, so vertical and square
versions don't look cramped. All brand colors and logo paths come from
brand config; per-crane text comes from the job config.
"""

import base64
import os
import cairosvg

# ---- Brand constants (Atlas Polar) -------------------------------------
BLUE = "#004B8D"
GREY = "#6B7A72"
RED = "#D52B1F"

# Aspect ratio canvas sizes
RATIOS = {
    "16x9": (1920, 1080),
    "9x16": (1080, 1920),
    "1x1": (1080, 1080),
}


def _b64(path):
    """Base64-encode an image. If it's an SVG, rasterize to PNG first so it
    can be embedded as a raster <image> reliably across renderers."""
    if path.lower().endswith(".svg"):
        png_path = path + ".raster.png"
        # Rasterize at a generous width to keep logo crisp when scaled up.
        cairosvg.svg2png(url=path, write_to=png_path, output_width=1400)
        path = png_path
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _cover_photo(src_path, tw, th, bias_y, out_path):
    """Scale+crop a photo to cover the target box, biased vertically."""
    from PIL import Image
    img = Image.open(src_path).convert("RGB")
    w, h = img.size
    scale = max(tw / w, th / h)
    nw, nh = int(w * scale + 0.5), int(h * scale + 0.5)
    r = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - tw) // 2
    y = int((nh - th) * bias_y)
    r.crop((x, y, x + tw, y + th)).save(out_path)
    return out_path


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# Approx character-width factor for Arial Bold/Black (em fraction per char).
# Used to fit titles to the canvas without a full font-metrics engine.
def _text_width(s, size, factor=0.58):
    return len(s) * size * factor


def _fit_title(text, size, max_width, min_size=44):
    """Return (lines, size). Shrink font until the text fits max_width; if it
    still doesn't fit at min_size, wrap into two balanced lines."""
    if _text_width(text, size) <= max_width:
        return [text], size
    # try shrinking
    s = size
    while s > min_size:
        s -= 4
        if _text_width(text, s) <= max_width:
            return [text], s
    # wrap into two lines at the nearest space to the middle
    words = text.split()
    if len(words) > 1:
        best_i, best_diff = 1, 10**9
        for i in range(1, len(words)):
            left = " ".join(words[:i])
            right = " ".join(words[i:])
            diff = abs(len(left) - len(right))
            if diff < best_diff:
                best_diff, best_i = diff, i
        lines = [" ".join(words[:best_i]), " ".join(words[best_i:])]
        # shrink wrapped lines to fit too
        s = size
        while s > min_size and max(_text_width(l, s) for l in lines) > max_width:
            s -= 4
        return lines, s
    return [text], min_size


def render_opening(cfg, ratio, photo_bg_b64, white_logo_b64, out_png):
    """Opening slide: photo background, white logo, title block bottom-left."""
    W, H = RATIOS[ratio]
    logo_native = 510 / 110  # w/h of AP-Logo-White.png

    # Per-ratio layout tuning
    if ratio == "16x9":
        logo_w, lx, ly = 440, 90, 70
        title_size, sub_size, kick_size = 104, 46, 34
        title_x = 90
        title_y = H - 115
        kick_y = H - 225
        sub_y = H - 55
    elif ratio == "9x16":
        logo_w, lx, ly = 460, 60, 90
        title_size, sub_size, kick_size = 92, 44, 32
        title_x = 70
        title_y = H - 360
        kick_y = H - 460
        sub_y = H - 290
    else:  # 1x1
        logo_w, lx, ly = 420, 70, 70
        title_size, sub_size, kick_size = 84, 42, 30
        title_x = 80
        title_y = H - 150
        kick_y = H - 250
        sub_y = H - 95

    logo_h = int(logo_w / logo_native)

    # Title may overflow on narrow ratios; fit it to the canvas width.
    raw_title = cfg["title"]
    subtitle = _esc(cfg["subtitle"])
    kicker = _esc(cfg["kicker"])

    max_title_w = W - title_x - 60
    title_lines, title_size = _fit_title(raw_title, title_size, max_title_w)

    # Build title tspans, stacking upward if wrapped so the block sits above subtitle.
    line_gap = int(title_size * 1.02)
    n = len(title_lines)
    # top line y so the last line ends at title_y
    first_y = title_y - line_gap * (n - 1)
    title_svg = ""
    for i, ln in enumerate(title_lines):
        ly_i = first_y + line_gap * i
        title_svg += (f'<text x="{title_x}" y="{ly_i}" font-family="Arial Black, Arial, sans-serif" '
                      f'font-size="{title_size}" font-weight="bold" fill="#ffffff">{_esc(ln)}</text>\n')
    # push kicker above the (possibly taller) title block
    kick_y = first_y - title_size - 18

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs>
<linearGradient id="scrim" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="#001a33" stop-opacity="0.78"/>
<stop offset="38%" stop-color="#001a33" stop-opacity="0.15"/>
<stop offset="68%" stop-color="#001a33" stop-opacity="0.35"/>
<stop offset="100%" stop-color="#001a33" stop-opacity="0.90"/>
</linearGradient>
</defs>
<image href="data:image/png;base64,{photo_bg_b64}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice"/>
<rect width="{W}" height="{H}" fill="url(#scrim)"/>
<rect x="0" y="0" width="{W}" height="12" fill="{RED}"/>
<rect x="0" y="{H-12}" width="{W}" height="12" fill="{RED}"/>
<image href="data:image/png;base64,{white_logo_b64}" x="{lx}" y="{ly}" width="{logo_w}" height="{logo_h}"/>
<text x="{title_x+6}" y="{kick_y}" font-family="Arial, sans-serif" font-size="{kick_size}" letter-spacing="6" fill="#ffffff" font-weight="bold">{kicker}</text>
{title_svg}
<text x="{title_x+6}" y="{sub_y}" font-family="Arial, sans-serif" font-size="{sub_size}" fill="#e8e8e8">{subtitle}</text>
</svg>'''
    cairosvg.svg2png(bytestring=svg.encode(), write_to=out_png,
                     output_width=W, output_height=H)
    return out_png


def render_closing(cfg, ratio, color_logo_b64, out_png):
    """Closing slide: white background, full-color logo, CTA."""
    W, H = RATIOS[ratio]
    logo_native = 475.7 / 104.8

    if ratio == "16x9":
        logo_w, logo_y = 690, 150
        kick_y, head_y, sub_y = 470, 600, 675
        cta1_y, cta2_y, rule_y = 838, 918, 745
        head_size = 96
    elif ratio == "9x16":
        logo_w, logo_y = 720, 360
        kick_y, head_y, sub_y = 760, 920, 1010
        cta1_y, cta2_y, rule_y = 1240, 1340, 1130
        head_size = 104
    else:  # 1x1
        logo_w, logo_y = 660, 170
        kick_y, head_y, sub_y = 430, 560, 635
        cta1_y, cta2_y, rule_y = 790, 880, 700
        head_size = 88

    logo_h = int(logo_w / logo_native)
    logo_x = (W - logo_w) / 2

    head = _esc(cfg["closing_headline"])
    sub = _esc(cfg["closing_sub"])
    kicker = _esc(cfg["closing_kicker"])
    phone = _esc(cfg["phone"])
    website = _esc(cfg["website"])

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<rect width="{W}" height="{H}" fill="#ffffff"/>
<rect x="0" y="0" width="{W}" height="12" fill="{RED}"/>
<rect x="0" y="{H-12}" width="{W}" height="12" fill="{RED}"/>
<image href="data:image/png;base64,{color_logo_b64}" x="{logo_x}" y="{logo_y}" width="{logo_w}" height="{logo_h}"/>
<text x="{W/2}" y="{kick_y}" text-anchor="middle" font-family="Arial, sans-serif" font-size="34" letter-spacing="8" fill="{RED}" font-weight="bold">{kicker}</text>
<text x="{W/2}" y="{head_y}" text-anchor="middle" font-family="Arial Black, Arial, sans-serif" font-size="{head_size}" font-weight="bold" fill="{BLUE}">{head}</text>
<text x="{W/2}" y="{sub_y}" text-anchor="middle" font-family="Arial, sans-serif" font-size="50" fill="{GREY}">{sub}</text>
<line x1="{W/2-250}" y1="{rule_y}" x2="{W/2+250}" y2="{rule_y}" stroke="{GREY}" stroke-width="2" opacity="0.4"/>
<text x="{W/2}" y="{cta1_y}" text-anchor="middle" font-family="Arial, sans-serif" font-size="56" font-weight="bold" fill="{BLUE}">{phone}</text>
<text x="{W/2}" y="{cta2_y}" text-anchor="middle" font-family="Arial, sans-serif" font-size="56" font-weight="bold" fill="{BLUE}">{website}</text>
</svg>'''
    cairosvg.svg2png(bytestring=svg.encode(), write_to=out_png,
                     output_width=W, output_height=H)
    return out_png


def render_thumbnail(cfg, photo_bg_b64, white_logo_b64, out_png):
    """YouTube thumbnail — 16:9 only, punchy two-tone headline."""
    W, H = RATIOS["16x9"]
    logo_native = 510 / 110
    logo_w = 520
    logo_h = int(logo_w / logo_native)

    line1 = _esc(cfg["thumb_line1"])
    line2 = _esc(cfg["thumb_line2"])
    spec = _esc(cfg["thumb_spec"])

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs>
<linearGradient id="tscrim" x1="0" y1="0" x2="1" y2="0">
<stop offset="0%" stop-color="#001a33" stop-opacity="0.92"/>
<stop offset="45%" stop-color="#001a33" stop-opacity="0.55"/>
<stop offset="100%" stop-color="#001a33" stop-opacity="0.05"/>
</linearGradient>
</defs>
<image href="data:image/png;base64,{photo_bg_b64}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice"/>
<rect width="{W}" height="{H}" fill="url(#tscrim)"/>
<rect x="0" y="150" width="22" height="780" fill="{RED}"/>
<text x="80" y="330" font-family="Arial Black, Arial, sans-serif" font-size="150" font-weight="bold" fill="#ffffff">{line1}</text>
<text x="84" y="470" font-family="Arial Black, Arial, sans-serif" font-size="150" font-weight="bold" fill="{RED}">{line2}</text>
<text x="88" y="585" font-family="Arial, sans-serif" font-size="60" fill="#ffffff" font-weight="bold">{spec}</text>
<image href="data:image/png;base64,{white_logo_b64}" x="80" y="850" width="{logo_w}" height="{logo_h}"/>
</svg>'''
    cairosvg.svg2png(bytestring=svg.encode(), write_to=out_png,
                     output_width=W, output_height=H)
    return out_png


def render_all_slides(cfg, brand, workdir):
    """Render opening+closing for all ratios, plus the 16:9 thumbnail.
    Returns dict of {key: path}.

    Photo selection per ratio: if the config provides a ratio-specific photo
    (via cfg['_photo_path_<ratio>']), it is used for that ratio; otherwise the
    default cfg['_photo_path'] is cropped to fit. This lets you supply a
    purpose-shot vertical image for 9x16 (and optionally a square one for 1x1)
    while a single landscape photo still works on its own.
    """
    default_photo = cfg["_photo_path"]
    white_logo_b64 = _b64(brand["white_logo"])
    color_logo_b64 = _b64(brand["color_logo"])
    out = {}

    bias = {"16x9": 0.45, "9x16": 0.40, "1x1": 0.45}
    for ratio, (W, H) in RATIOS.items():
        photo = cfg.get(f"_photo_path_{ratio}") or default_photo
        bg = os.path.join(workdir, f"bg_{ratio}.png")
        _cover_photo(photo, W, H, bias[ratio], bg)
        bg_b64 = _b64(bg)

        op = os.path.join(workdir, f"opening_{ratio}.png")
        render_opening(cfg, ratio, bg_b64, white_logo_b64, op)
        out[f"opening_{ratio}"] = op

        cl = os.path.join(workdir, f"closing_{ratio}.png")
        render_closing(cfg, ratio, color_logo_b64, cl)
        out[f"closing_{ratio}"] = cl

    # thumbnail uses the 16:9 background (always the landscape framing)
    bg169_b64 = _b64(os.path.join(workdir, "bg_16x9.png"))
    th = os.path.join(workdir, "thumbnail.png")
    render_thumbnail(cfg, bg169_b64, white_logo_b64, th)
    out["thumbnail"] = th

    return out
