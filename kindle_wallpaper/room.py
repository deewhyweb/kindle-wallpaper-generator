"""Place the rendered bookcase in an AI-generated room.

1. Render the bookcase at the exact pixel size it will occupy in the final 1920x1080 image.
2. Send a 1536x1024 canvas with a scaled copy of it to the OpenAI image edit API,
   with everything around it masked as editable, so the model paints a room around it.
3. Upscale the room to the final size, colour-grade our bookcase towards the model's
   lighting, and paste the original pixels back so every title stays crisp.

Generated rooms are cached in data/rooms/, so re-rendering with a different sort,
theme or seed doesn't call the image API again (use --regenerate for a new room).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

PROMPT = (
    "Photorealistic interior photograph used as a video-call background, eye level, 35mm lens, "
    "gentle depth of field, {photo}. A bookcase full of books stands against the back wall in the centre "
    "of the frame — keep that bookcase, its books and its proportions exactly as given and make it "
    "look naturally lit and grounded in the room with a soft contact shadow. {decor}"
    "Make the rest a warm, lived-in room: {room}. Either side of the bookcase, include a lit lamp "
    "casting a soft pool of light and real greenery such as a large potted plant, plus a piece of "
    "furniture or side table with a few objects on it, so the scene feels like a real home rather "
    "than a showroom. No people, no readable text, no logos."
)

DECOR_PROMPT = (
    "The empty gaps on its shelves are for shelf ornaments: fill each gap with one object or a small "
    "group sitting on the shelf and sized to fit it, in keeping with the room — for example "
    "{ornaments}, or a small plant. Vary them from shelf to shelf. "
)

FINAL = (1920, 1080)
AI_SIZE = (1536, 1024)
SCALE = FINAL[0] / AI_SIZE[0]  # 1.25; the AI image is upscaled to 1920x1280 then cropped to 1080 tall
Y_OFFSET = (AI_SIZE[1] * SCALE - FINAL[1]) // 2


def bookcase_box(width: float = 0.5) -> tuple[int, int, int, int]:
    """Where the bookcase sits in the final image: (x, y, w, h). `width` is a fraction of the frame."""
    W, H = FINAL
    w = int(W * width)
    h = min(int(H * 0.8), int(w * 0.85))
    return (W - w) // 2, int(H * 0.9) - h, w, h


def keep_mask(size: tuple[int, int], slots: list) -> Image.Image:
    """255 where our bookcase pixels win, 0 in the ornament slots the image model fills."""
    m = Image.new("L", size, 255)
    for x0, y0, x1, y1 in slots:
        m.paste(0, (x0, y0, x1, y1))
    return m


def _to_ai(x: float, y: float) -> tuple[int, int]:
    return round(x / SCALE), round((y + Y_OFFSET) / SCALE)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_room(bookcase: Image.Image, slots: list, box, prompt: str, model: str, quality: str) -> Image.Image:
    from openai import BadRequestError, OpenAI

    x, y, w, h = box
    (ax0, ay0), (ax1, ay1) = _to_ai(x, y), _to_ai(x + w, y + h)
    canvas = Image.new("RGBA", AI_SIZE, (0, 0, 0, 0))
    small = bookcase.convert("RGBA")
    small.putalpha(keep_mask(bookcase.size, slots))
    canvas.paste(small.resize((ax1 - ax0, ay1 - ay0), Image.Resampling.LANCZOS), (ax0, ay0))
    # Transparent pixels in the mask = "paint here"; the bookcase stays opaque.
    mask = canvas.copy()

    client = OpenAI()
    kwargs = dict(
        model=model,
        image=("scene.png", _png(canvas), "image/png"),
        mask=("mask.png", _png(mask), "image/png"),
        prompt=prompt,
        size=f"{AI_SIZE[0]}x{AI_SIZE[1]}",
        quality=quality,
        input_fidelity="high",
    )
    print(f"Generating room with {model} (quality={quality}); this can take a minute...")
    try:
        result = client.images.edit(**kwargs)
    except BadRequestError as e:
        if "input_fidelity" not in str(e):
            raise
        kwargs.pop("input_fidelity")
        result = client.images.edit(**kwargs)
    return Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json))).convert("RGB")


def _match_colors(src: Image.Image, ref: Image.Image, strength: float) -> Image.Image:
    """Shift src's per-channel mean/contrast towards ref's (Reinhard-style transfer)."""
    s, r = ImageStat.Stat(src), ImageStat.Stat(ref)
    bands = []
    for i, band in enumerate(src.split()):
        sm, ss = s.mean[i], max(1.0, s.stddev[i])
        rm, rs = r.mean[i], max(1.0, r.stddev[i])
        # Clamped so a model that badly repaints the bookcase can't wreck our colours.
        k = 1 + strength * (min(1.25, max(0.8, rs / ss)) - 1)
        off = strength * max(-30.0, min(30.0, rm - sm))
        bands.append(band.point(lambda v, sm=sm, k=k, off=off: max(0, min(255, int((v - sm) * k + sm + off)))))
    return Image.merge("RGB", bands)


def composite(room_ai: Image.Image, bookcase: Image.Image, slots: list, box, grade: float = 0.45) -> Image.Image:
    W, H = FINAL
    big = room_ai.resize((W, round(AI_SIZE[1] * SCALE)), Image.Resampling.LANCZOS)
    final = big.crop((0, Y_OFFSET, W, Y_OFFSET + H))
    x, y, w, h = box
    # The model's own repaint of the bookcase tells us how the room lights it; grade ours to match.
    graded = _match_colors(bookcase.convert("RGB"), final.crop((x, y, x + w, y + h)), grade)
    # Feather the edge a couple of pixels so it sits in the scene rather than on top of it.
    # Leave the model's ornaments showing in the slots.
    edge = Image.new("L", (w, h), 0)
    edge.paste(keep_mask((w - 4, h - 4), [(a - 2, b - 2, c - 2, d - 2) for a, b, c, d in slots]), (2, 2))
    final.paste(graded, (x, y), edge.filter(ImageFilter.GaussianBlur(1.5)))
    return final


def room_key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:12]


def make_room_wallpaper(
    bookcase: Image.Image,
    slots: list,
    box,
    prompt: str,
    rooms_dir: Path,
    model: str,
    quality: str,
    finish: str,
    regenerate: bool = False,
) -> Image.Image:
    rooms_dir.mkdir(parents=True, exist_ok=True)
    # Ornament positions are part of the key: a room painted for one layout won't fit another.
    key = room_key(prompt, model, quality, finish, list(box), [list(s) for s in slots])
    cached = rooms_dir / f"{key}.png"
    if cached.exists() and not regenerate:
        print(f"Reusing cached room {cached} (pass --regenerate for a new one)")
        room = Image.open(cached).convert("RGB")
    else:
        room = generate_room(bookcase, slots, box, prompt, model, quality)
        room.save(cached)
        (rooms_dir / f"{key}.json").write_text(json.dumps({"prompt": prompt, "model": model, "finish": finish}, indent=2))
        print(f"Saved room to {cached}")
    return composite(room, bookcase, slots, box)
