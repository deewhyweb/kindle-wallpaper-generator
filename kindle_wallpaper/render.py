"""Render a bookcase image from a list of books."""

from __future__ import annotations

import colorsys
import hashlib
import math
import random
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

# ---------------------------------------------------------------- fonts

FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Baskerville.ttc",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/Avenir Next Condensed.ttc",
    "/System/Library/Fonts/Supplemental/Didot.ttc",
    "/System/Library/Fonts/Supplemental/Copperplate.ttc",
    "/System/Library/Fonts/Supplemental/Gill Sans.ttc",
    "/System/Library/Fonts/Supplemental/Rockwell.ttc",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    # Windows
    "C:/Windows/Fonts/georgiab.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
FONTS = [f for f in FONT_CANDIDATES if Path(f).exists()]

_SUP = "/System/Library/Fonts/Supplemental/"
TYPEFACE_CANDIDATES = {
    "classic_serif": [_SUP + "Baskerville.ttc", _SUP + "Big Caslon.ttf", "/System/Library/Fonts/Supplemental/Hoefler Text.ttc",
                      _SUP + "Georgia Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "C:/Windows/Fonts/georgiab.ttf"],
    "modern_serif": [_SUP + "Didot.ttc", _SUP + "Bodoni 72.ttc", _SUP + "Georgia Bold.ttf",
                     "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"],
    "bold_sans": [_SUP + "Futura.ttc", _SUP + "Gill Sans.ttc", "/System/Library/Fonts/HelveticaNeue.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "condensed_sans": ["/System/Library/Fonts/Avenir Next Condensed.ttc", _SUP + "DIN Condensed Bold.ttf",
                       _SUP + "Impact.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "display": [_SUP + "Copperplate.ttc", _SUP + "Rockwell.ttc", _SUP + "American Typewriter.ttc", _SUP + "Didot.ttc"],
}
TYPEFACES = {k: [f for f in v if Path(f).exists()] or FONTS for k, v in TYPEFACE_CANDIDATES.items()}

# Where ornament slots go along each shelf (fractions of the way through its books).
DECOR_PATTERNS = [(1.0, 0.35), (0.0, 0.7), (0.5, 0.0), (0.65, 1.0), (0.3, 0.85)]

# Bookcase finishes: (frame colour, back panel colour, grain strength)
FINISHES = {
    "walnut": ((122, 78, 46), (67, 43, 25), 1.0),
    "oak": ((178, 136, 88), (120, 88, 56), 0.9),
    "mahogany": ((112, 46, 32), (60, 26, 20), 1.0),
    "white": ((236, 232, 224), (206, 200, 190), 0.15),
    "black": ((44, 42, 40), (28, 27, 26), 0.35),
}


@lru_cache(maxsize=2048)
def font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


# ---------------------------------------------------------------- colors

CLASSIC_BINDINGS = [
    (110, 28, 32), (24, 40, 74), (28, 66, 46), (176, 136, 52), (220, 208, 180),
    (30, 30, 32), (24, 92, 96), (178, 82, 34), (78, 38, 78), (96, 96, 100),
    (140, 50, 40), (52, 82, 120), (200, 170, 120), (60, 50, 40),
]
GOLD = (222, 196, 120)


def luminance(c) -> float:
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


def shade(c, f: float):
    return tuple(max(0, min(255, int(v * f))) for v in c[:3])


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_color_for(bg, rng: random.Random):
    """Most legible of dark / cream text, with gold foil when it is clearly readable."""
    if contrast(GOLD, bg) >= 4 and rng.random() < 0.4:
        return GOLD
    return max([(28, 24, 22), (240, 236, 226)], key=lambda c: contrast(c, bg))


def cover_colors(path: Path):
    """Pick a (main, accent) pair from a cover image, favouring saturated, non-white colors."""
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    im.thumbnail((64, 64))
    q = im.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    scored = []
    for count, idx in q.getcolors():
        rgb = tuple(pal[idx * 3: idx * 3 + 3])
        _, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in rgb))
        penalty = 0.25 if (v > 0.92 and s < 0.12) else 1.0  # plain white backgrounds
        scored.append((count * (0.3 + s) * penalty, rgb))
    scored.sort(reverse=True)
    main = shade(scored[0][1], 0.88)
    accent = scored[1][1] if len(scored) > 1 else shade(main, 1.4)
    return main, accent


# ---------------------------------------------------------------- data

@dataclass
class Book:
    title: str
    author: str
    cover: Path | None
    color: tuple
    accent: tuple
    rng: random.Random
    # Per-book shape, as fractions of the shelf height (so layout can rescale).
    hfrac: float = 0.8
    wfrac: float = 0.16
    face_out: bool = False
    font_path: str | None = None
    style: int = 0
    genre: str = "other"
    notability: int = 3
    order: int = 0  # position in the library (0 = most recent)
    gilt: bool = False
    _cover_img: Image.Image | None = field(default=None, repr=False)

    @property
    def cover_img(self) -> Image.Image | None:
        if self._cover_img is None and self.cover and self.cover.exists():
            try:
                self._cover_img = Image.open(self.cover).convert("RGB")
            except Exception:
                self.cover = None
        return self._cover_img


def clean_title(title: str) -> str:
    t = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", title)  # "(Series Book 3)", "[Kindle Edition]"
    t = re.split(r":\s| - | — ", t)[0]  # drop subtitles
    return t.strip() or title.strip()


def surname(name: str) -> str:
    parts = [p for p in name.replace(",", " ").split() if p.lower().strip(".") not in ("jr", "sr", "ii", "iii", "iv", "phd")]
    return parts[-1] if parts else name


def hex_rgb(h: str):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) if h and len(h) == 7 else None


def apply_style(b: Book, s: dict, rng: random.Random) -> None:
    """Turn Claude's per-book styling (see curate.py) into drawing parameters."""
    b.genre = s.get("genre", "other")
    b.notability = int(s.get("notability", 3))
    b.title = s.get("spine_title") or b.title
    b.font_path = rng.choice(TYPEFACES.get(s.get("typeface"), FONTS) or [None])
    suggested = hex_rgb(s.get("spine_color", ""))
    binding = s.get("binding")
    if binding == "leather_gilt":
        base = suggested or b.color
        b.color = shade(base, min(1.0, 0.3 / max(0.05, luminance(base))))  # deep leather tones
        b.accent, b.gilt, b.style = GOLD, True, 4
        b.wfrac = min(0.26, b.wfrac * 1.15)
    elif binding == "cloth_classic":
        b.color = suggested or b.color
        b.style = 1
        b.gilt = luminance(b.color) < 0.4
    elif binding == "paperback":
        b.style = 5
        b.hfrac = rng.uniform(0.60, 0.72)
        b.wfrac *= 0.85
    elif binding == "technical":
        b.style = 2
    elif binding == "pulp":
        b.style = 3
        b.hfrac = rng.uniform(0.58, 0.68)
        b.wfrac *= 0.8
    else:  # modern_hardcover
        b.style = rng.choice([0, 3])
    if b.cover is None and suggested and binding not in ("leather_gilt",):
        b.color = suggested


def make_books(raw: list[dict], covers_dir: Path | None, seed: int, styles: dict | None = None) -> list[Book]:
    books = []
    for i, r in enumerate(raw):
        key = r.get("asin") or r.get("title", "")
        rng = random.Random(f"{seed}-{key}")
        cover = covers_dir / f"{r['asin']}.jpg" if covers_dir and r.get("asin") else None
        cols = cover_colors(cover) if cover and cover.exists() else None
        if cols is None:
            h = int(hashlib.md5(key.encode()).hexdigest(), 16)
            main = CLASSIC_BINDINGS[h % len(CLASSIC_BINDINGS)]
            cols = (main, GOLD if luminance(main) < 0.5 else (90, 30, 30))
            cover = None
        authors = r.get("authors") or []
        title = clean_title(r.get("title", ""))
        b = Book(
            title=title,
            author=surname(authors[0]) if authors else "",
            cover=cover,
            color=cols[0],
            accent=cols[1],
            rng=rng,
            hfrac=rng.uniform(0.70, 0.90),
            # Long titles tend to have fatter spines; add noise so it isn't uniform.
            wfrac=min(0.24, rng.uniform(0.10, 0.17) + len(title) * 0.0012),
            font_path=rng.choice(FONTS) if FONTS else None,
            style=rng.randrange(4),
            order=i,
        )
        if styles and r.get("asin") in styles:
            apply_style(b, styles[r["asin"]], rng)
        books.append(b)
    return books


def sort_books(books: list[Book], how: str, seed: int) -> list[Book]:
    if how == "title":
        return sorted(books, key=lambda b: re.sub(r"^(the|a|an)\s+", "", b.title.lower()))
    if how == "author":
        return sorted(books, key=lambda b: (b.author.lower(), b.title.lower()))
    if how == "color":
        def hue(b):
            h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in b.color))
            return (0 if s > 0.2 else 1, h, v)  # rainbow first, greys/blacks at the end
        return sorted(books, key=hue)
    if how == "genre":
        sizes = {}
        for b in books:
            sizes[b.genre] = sizes.get(b.genre, 0) + 1
        return sorted(books, key=lambda b: (-sizes[b.genre], b.genre, b.author.lower(), b.title.lower()))
    if how == "random":
        books = books[:]
        random.Random(seed).shuffle(books)
    return books  # "recent": keep library order


# ---------------------------------------------------------------- texture helpers

def smooth_noise(n: int, rng: random.Random, scale: int = 40) -> list[float]:
    pts = [rng.uniform(-1, 1) for _ in range(n // scale + 3)]
    out = []
    for i in range(n):
        x = i / scale
        a, b = pts[int(x)], pts[int(x) + 1]
        t = x - int(x)
        t = t * t * (3 - 2 * t)
        out.append(a + (b - a) * t)
    return out


def wood(w: int, h: int, base, rng: random.Random, vertical: bool = False, grain: float = 1.0) -> Image.Image:
    """Procedural wood grain running along the long axis (grain=0 gives flat paint)."""
    if vertical:
        return wood(h, w, base, rng, grain=grain).rotate(90, expand=True)
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    broad = smooth_noise(h, rng, scale=max(6, h // 6))
    fine = smooth_noise(h, rng, scale=2)
    for y in range(h):
        f = 1 + grain * (0.07 * broad[y] + 0.04 * fine[y])
        d.line([(0, y), (w, y)], fill=shade(base, f))
    # Long wavy grain streaks.
    for _ in range(max(2, h // 5)):
        y0 = rng.uniform(0, h)
        amp, freq, phase = rng.uniform(0.5, 3), rng.uniform(0.002, 0.01), rng.uniform(0, 6.28)
        col = shade(base, 1 - grain * rng.uniform(0.08, 0.22))
        pts = [(x, y0 + amp * math.sin(x * freq + phase)) for x in range(0, w + 20, 20)]
        d.line(pts, fill=col, width=1)
    return img


# ---------------------------------------------------------------- book drawing

def fit_text(text: str, font_path, max_len: int, max_size: int, min_size: int = 9):
    size = max_size
    while size > min_size:
        f = font(font_path, size)
        if f.getlength(text) <= max_len:
            return text, f
        size -= 1
    f = font(font_path, min_size)
    while text and f.getlength(text + "…") > max_len:
        text = text[:-1]
    return (text.rstrip() + "…") if text else "", f


def rotated_text(text: str, f, color, length: int, thickness: int) -> Image.Image:
    """Text laid out horizontally, then rotated to read top-to-bottom like a spine."""
    layer = Image.new("RGBA", (length, thickness), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((length / 2, thickness / 2), text, font=f, fill=color + (255,), anchor="mm")
    return layer.transpose(Image.Transpose.ROTATE_270)


def spine_shading(w: int, h: int) -> Image.Image:
    """Multiply mask that makes a flat rectangle look like a rounded spine."""
    strip = Image.new("L", (w, 1))
    for x in range(w):
        t = x / max(1, w - 1)
        v = 0.72 + 0.33 * math.sin(math.pi * min(1, t * 1.15))
        strip.putpixel((x, 0), int(255 * min(1, v)))
    return strip.resize((w, h)).convert("RGB")


def draw_spine(b: Book, w: int, h: int) -> Image.Image:
    rng = random.Random(b.rng.random())
    img = Image.new("RGB", (w, h), b.color)
    d = ImageDraw.Draw(img)
    tc = GOLD if b.gilt and contrast(GOLD, b.color) >= 2.5 else text_color_for(b.color, rng)
    band = b.accent if abs(luminance(b.accent) - luminance(b.color)) > 0.15 else tc

    top_pad, bottom_pad = int(h * 0.06), int(h * 0.06)
    if b.style == 1:  # thin bands top and bottom
        for y in (int(h * 0.05), int(h * 0.92)):
            d.rectangle([0, y, w, y + max(2, h // 90)], fill=band)
            d.rectangle([0, y + h // 45, w, y + h // 45 + max(1, h // 160)], fill=band)
        top_pad, bottom_pad = int(h * 0.11), int(h * 0.12)
    elif b.style == 2:  # contrasting label block holding the title
        label = shade(b.color, 0.5) if luminance(b.color) > 0.3 else shade(band, 1.1)
        d.rectangle([int(w * 0.1), int(h * 0.05), int(w * 0.9), int(h * 0.7)], fill=label)
        tc = text_color_for(label, rng)
        top_pad = int(h * 0.08)
    elif b.style == 3:  # colored cap at the top
        d.rectangle([0, 0, w, int(h * 0.13)], fill=band)
        top_pad = int(h * 0.17)
    elif b.style == 4:  # leather: raised ribs with gilt rules either side
        rib = max(3, h // 60)
        for fy in (0.07, 0.30, 0.74, 0.93):
            y = int(h * fy)
            d.rectangle([0, y - rib, w, y + rib], fill=shade(b.color, 1.35))
            d.rectangle([0, y + rib, w, y + rib + 1], fill=shade(b.color, 0.6))
            for gy in (y - rib - 3, y + rib + 3):
                d.line([(0, gy), (w, gy)], fill=GOLD, width=1)
        top_pad, bottom_pad = int(h * 0.34), int(h * 0.09)
    elif b.style == 5:  # paperback: publisher block at the foot
        foot = int(h * 0.1)
        d.rectangle([0, h - foot, w, h], fill=band)
        mark = max(4, int(w * 0.35))
        cx, cy = w // 2, h - foot // 2
        d.ellipse([cx - mark // 2, cy - mark // 2, cx + mark // 2, cy + mark // 2],
                  fill=text_color_for(band, rng))
        top_pad, bottom_pad = int(h * 0.05), foot + int(h * 0.03)

    img = ImageChops.multiply(img, spine_shading(w, h))
    img = img.convert("RGBA")

    thick = int(w * 0.8)
    author_len = int(h * 0.2) if b.author and h > 90 and b.style != 4 else 0
    title_len = h - top_pad - bottom_pad - author_len - (int(h * 0.03) if author_len else 0)
    if b.style == 2:
        title_len = int(h * 0.59)
    elif b.style == 4:
        title_len = int(h * 0.36)
    if b.title and title_len > 20:
        text, f = fit_text(b.title, b.font_path, title_len, max(9, int(w * 0.55)))
        t_img = rotated_text(text, f, tc, title_len, thick)
        img.alpha_composite(t_img, ((w - thick) // 2, top_pad))
    if author_len:
        tc = text_color_for(b.color, rng) if b.style == 2 else tc
        text, f = fit_text(b.author.upper(), b.font_path, author_len, max(8, int(w * 0.38)), 8)
        a_img = rotated_text(text, f, tc, author_len, thick)
        img.alpha_composite(a_img, ((w - thick) // 2, h - bottom_pad - author_len))
    return img


def draw_face_out(b: Book, h: int) -> Image.Image:
    cov = b.cover_img
    aspect = min(0.8, max(0.55, cov.width / cov.height))
    w = int(h * aspect)
    img = ImageOps.fit(cov, (w, h), method=Image.Resampling.LANCZOS).convert("RGBA")
    # Subtle edge darkening so it reads as a physical object.
    edge = Image.new("L", (w, h), 255)
    ImageDraw.Draw(edge).rectangle([0, 0, w - 1, h - 1], outline=200, width=2)
    return Image.composite(img, Image.new("RGBA", (w, h), (0, 0, 0, 255)), edge)


# ---------------------------------------------------------------- layout

@dataclass
class Placed:
    img: Image.Image
    x: int
    y_bottom: int
    angle: float = 0.0


def item_width(b: Book, row_h: int) -> int:
    if b.face_out:
        cov = b.cover_img
        return int(row_h * 0.82 * min(0.8, max(0.55, cov.width / cov.height))) + 6
    return max(14, int(b.wfrac * row_h)) + 1


def plan_rows(books: list[Book], n_rows: int, row_h: int, inner_w: int) -> list[list[Book]] | None:
    total = sum(item_width(b, row_h) for b in books)
    target = total / n_rows
    rows, cur, cur_w = [], [], 0
    for b in books:
        bw = item_width(b, row_h)
        if cur and (cur_w + bw > inner_w or (cur_w + bw / 2 > target and len(rows) < n_rows - 1)):
            rows.append(cur)
            cur, cur_w = [], 0
        cur.append(b)
        cur_w += bw
    rows.append(cur)
    if len(rows) > n_rows or any(sum(item_width(b, row_h) for b in r) > inner_w for r in rows):
        return None
    return rows


def render(
    raw_books: list[dict],
    covers_dir: Path | None,
    out: Path | None,
    size=(1920, 1080),
    sort: str = "author",
    shelves: int | None = None,
    face_out_every: int = 14,
    seed: int = 7,
    finish: str = "walnut",
    styles: dict | None = None,
    max_shelves: int = 5,
    decor: list | None = None,
) -> Image.Image:
    """Draw the bookcase. If `decor` is a list, leave empty slots on the shelves for
    ornaments (plants, lamps...) and append each slot's (x0, y0, x1, y1) box to it."""
    W, H = size
    rng = random.Random(seed)
    wood_color, back_color, grain = FINISHES[finish]
    books = sort_books(make_books(raw_books, covers_dir, seed, styles), sort, seed)

    frame = int(H * 0.035)
    board = int(H * 0.026)
    inner_x0, inner_x1 = frame, W - frame
    inner_w = inner_x1 - inner_x0 - 2 * int(W * 0.006)

    def row_height(n):
        return (H - 2 * frame - (n - 1) * board) // n

    def slots_per_row(n):
        if decor is None:
            return 0
        return 2 if inner_w / row_height(n) > 6.5 else 1

    def reserve(n):  # shelf width held back for ornaments
        return int(slots_per_row(n) * 0.9 * row_height(n))

    # Mark some covers face-out for visual interest.
    with_cover = [b for b in books if b.cover_img is not None]
    if face_out_every > 0:
        for b in with_cover[face_out_every // 2::face_out_every]:
            b.face_out = True

    # Small library? Face out more covers so the shelves don't look empty.
    n_rows_min = 3
    rh = row_height(n_rows_min)
    for b in with_cover:
        if sum(item_width(x, rh) for x in books) > n_rows_min * inner_w * 0.45:
            break
        b.face_out = True

    candidates = [shelves] if shelves else list(range(n_rows_min, max(n_rows_min, max_shelves) + 1))
    rows = None
    for n in candidates:
        rows = plan_rows(books, n, row_height(n), int(inner_w * 0.95) - reserve(n))
        if rows:
            break
    if rows is None:
        rh = row_height(n)
        # Too many books: keep the most notable (then most recent) that fit, in display order.
        keep, used = set(), 0
        cap = n * (inner_w * 0.9 - reserve(n))
        for b in sorted(books, key=lambda b: (-b.notability, b.order)):
            used += item_width(b, rh)
            if used > cap:
                break
            keep.add(id(b))
        shown = [b for b in books if id(b) in keep]
        print(f"Showing {len(shown)} of {len(books)} books (most notable first); --max-shelves fits more.")
        rows = plan_rows(shown, n, rh, inner_w - reserve(n)) or [shown]
    while len(rows) < n:
        rows.append([])
    rh = row_height(n)

    # ---- the case itself
    canvas = wood(W, H, back_color, rng, grain=grain)  # back panel
    shadow = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shadow)
    items: list[Placed] = []

    for i, row in enumerate(rows):
        top = frame + i * (rh + board)
        bottom = top + rh
        x = inner_x0 + int(W * 0.006) + rng.randint(0, 12)
        upright = row[:]

        # Lay a few books flat in a stack when there is room.
        stack: list[Book] = []
        stack_w = 0
        slack = inner_w - sum(item_width(b, rh) for b in upright) - reserve(n)
        spine_books = [b for b in upright if not b.face_out]
        if len(spine_books) > 6 and rng.random() < 0.75:
            cand = spine_books[-rng.randint(2, 4):]
            stack_w = max(int(b.hfrac * rh) for b in cand)
            if slack + sum(item_width(b, rh) for b in cand) > stack_w + 20:
                stack = cand
                upright = [b for b in upright if b not in stack]
                slack += sum(item_width(b, rh) for b in cand) - stack_w
            else:
                stack_w = 0

        # Lots of room: split into two groups with the gap (and stack) between them,
        # so a half-full shelf doesn't leave one big empty block.
        if slack > inner_w * 0.15 and len(upright) >= 4:
            k = int(len(upright) * rng.uniform(0.4, 0.6))
            groups = [upright[:k], upright[k:]]
        else:
            groups = [upright]
        gaps = len(groups) - 1 + (1 if stack else 0)
        gap = slack // max(1, gaps) if len(groups) > 1 else 0

        def place_group(group: list[Book], x: int, lean: bool) -> int:
            for j, b in enumerate(group):
                if b.face_out:
                    img = draw_face_out(b, int(rh * 0.82))
                    items.append(Placed(img, x + 3, bottom))
                    x += img.width + 6
                    continue
                w, h = item_width(b, rh) - 1, int(b.hfrac * rh)
                img = draw_spine(b, w, h)
                if lean and j == len(group) - 1:
                    angle = rng.uniform(8, 14)  # top tips left, resting on its neighbour
                    rot = img.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
                    items.append(Placed(rot, x, bottom, angle))
                    x += rot.width
                else:
                    items.append(Placed(img, x, bottom))
                    x += w + 1 + (1 if rng.random() < 0.3 else 0)
            return x

        def place_stack(x: int) -> None:
            y = bottom
            for b in stack:
                w, h = item_width(b, rh) - 1, int(b.hfrac * rh)
                img = draw_spine(b, w, h).transpose(Image.Transpose.ROTATE_90)
                items.append(Placed(img, x + rng.randint(-5, 5), y))
                y -= img.height

        if decor is not None:
            # Split the row around one or two ornament slots, staggered from shelf to shelf.
            cuts = DECOR_PATTERNS[(i + seed) % len(DECOR_PATTERNS)][: slots_per_row(n) if len(upright) >= 3 else 1]
            slot_ws = [int(rh * rng.uniform(0.6, 0.9)) for _ in cuts]
            free = inner_w - sum(item_width(b, rh) for b in upright) - (stack_w + 8 if stack else 0) - sum(slot_ws)
            extra = max(-sum(slot_ws) * 0.3, min(free * 0.6, len(cuts) * rh * 0.4))  # grow (or shrink) to fit
            slot_ws = [w + int(extra / len(cuts)) for w in slot_ws]
            idx = sorted(round(c * len(upright)) for c in cuts)
            segs, prev = [], 0
            for c, sw in zip(idx, slot_ws):
                segs += [upright[prev:c], sw]
                prev = c
            segs.append(upright[prev:])
            x = inner_x0 + int(W * 0.006) + rng.randint(0, 8)
            for seg in segs:
                if isinstance(seg, int):
                    decor.append((x, top + 2, x + seg, bottom))
                    x += seg
                    if stack:  # a flat stack of books beside an ornament
                        place_stack(x + 4)
                        x += stack_w + 8
                        stack = []
                else:
                    x = place_group(seg, x, False)
            continue

        first = groups[0]
        can_lean = len(first) > 1 and not first[-1].face_out and not first[-2].face_out and rng.random() < 0.6
        lean = can_lean and (gap if len(groups) > 1 else slack) > rh * 0.45
        x = place_group(first, x, lean)
        if len(groups) > 1:
            if stack:
                place_stack(x + (gap - stack_w) // 2 + stack_w // 2)
            x = max(x + gap // 2, x + gap - (int(rh * 0.2) if lean else 0))
            place_group(groups[1], x if not stack else x + stack_w, False)
        elif stack:
            place_stack(inner_x1 - int(W * 0.006) - stack_w - rng.randint(4, 30))

    for p in items:
        a = p.img.split()[-1]
        shadow.paste(255, (p.x + 7, p.y_bottom - p.img.height + 4), a)
    # Shadows under each shelf board and down the sides of the case.
    for i in range(len(rows)):
        top = frame + i * (rh + board)
        sd.rectangle([inner_x0, top, inner_x1, top + int(rh * 0.08)], fill=150)
    sd.rectangle([inner_x0, 0, inner_x0 + 18, H], fill=160)
    shadow = shadow.filter(ImageFilter.GaussianBlur(H // 90))
    canvas = Image.composite(Image.new("RGB", (W, H), (12, 8, 6)), canvas, shadow.point(lambda v: int(v * 0.6)))

    canvas = canvas.convert("RGBA")
    for p in items:
        canvas.alpha_composite(p.img, (p.x, p.y_bottom - p.img.height))
    canvas = canvas.convert("RGB")

    # Frame and shelf boards drawn on top.
    light_wood = wood_color
    canvas.paste(wood(frame, H, light_wood, rng, vertical=True, grain=grain), (0, 0))
    canvas.paste(wood(frame, H, light_wood, rng, vertical=True, grain=grain), (W - frame, 0))
    canvas.paste(wood(W, frame, light_wood, rng, grain=grain), (0, 0))
    canvas.paste(wood(W, frame, shade(light_wood, 0.95), rng, grain=grain), (0, H - frame))
    d = ImageDraw.Draw(canvas)
    for i in range(1, len(rows)):
        y = frame + i * (rh + board) - board
        canvas.paste(wood(W - 2 * frame, board, light_wood, rng, grain=grain), (frame, y))
        d.line([(frame, y), (W - frame, y)], fill=shade(light_wood, 1.3), width=2)
        d.line([(frame, y + board - 1), (W - frame, y + board - 1)], fill=shade(light_wood, 0.6), width=2)
    d.line([(frame, H - frame), (W - frame, H - frame)], fill=shade(light_wood, 1.3), width=2)
    for x in (frame - 2, W - frame):
        d.line([(x, frame), (x, H - frame)], fill=shade(light_wood, 0.55), width=2)
    d.line([(frame, frame), (W - frame, frame)], fill=shade(light_wood, 0.55), width=2)

    # Warm light from above plus a soft vignette.
    vig = Image.new("L", (64, 36))
    for yy in range(36):
        for xx in range(64):
            dx, dy = (xx - 31.5) / 32, (yy - 10) / 30
            vig.putpixel((xx, yy), int(255 * max(0.55, 1.05 - 0.35 * (dx * dx + dy * dy))))
    vig = vig.resize((W, H), Image.Resampling.BICUBIC).convert("RGB")
    canvas = ImageChops.multiply(canvas, vig)
    warm = Image.new("RGB", (W, H), (255, 214, 160))
    canvas = Image.blend(canvas, ImageChops.multiply(canvas, warm), 0.15)

    shown = sum(len(r) for r in rows)
    print(f"Bookcase: {W}x{H}, {shown} books on {len(rows)} shelves")
    if out:
        save(canvas, out)
    return canvas


def save(img: Image.Image, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        img.convert("RGB").save(out, quality=92)
    else:
        img.save(out)
    print(f"Wrote {out}")
