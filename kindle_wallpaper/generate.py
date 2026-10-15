"""Have an image model paint the whole scene — room, bookcase, ornaments and your books.

Image models can't fit hundreds of legible titles, and they misspell, so this keeps the
book count modest and uses Claude on both sides of the image model:

1. Plan: Claude picks the arrangement (which books go on which shelf, spine vs face-out,
   where the ornaments go) and describes the room. The prompt is built from that plan.
2. Generate: the image model paints it. Face-out books get their real covers passed
   in as reference images.
3. Check: Claude looks at the result, reads every spine, and reports which titles came
   out right. If too many are wrong, we regenerate with that feedback; the best
   attempt wins.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import anthropic
from PIL import Image

from .curate import MODEL
from .render import clean_title, surname

OUT_SIZE = (1920, 1080)
AI_SIZE = "1536x1024"

BINDING_TEXT = {
    "leather_gilt": "dark leather binding with raised bands and gold-foil lettering",
    "cloth_classic": "cloth-bound hardcover",
    "modern_hardcover": "hardcover with a dust jacket",
    "paperback": "shorter paperback",
    "technical": "technical book with a white title label",
    "pulp": "vintage pulp paperback",
}
TYPEFACE_TEXT = {
    "classic_serif": "classic serif",
    "modern_serif": "elegant high-contrast serif",
    "bold_sans": "bold sans-serif",
    "condensed_sans": "condensed sans-serif",
    "display": "decorative display",
}
FINISH_TEXT = {
    "walnut": "dark walnut wood",
    "oak": "light oak",
    "mahogany": "rich mahogany",
    "white": "white-painted",
    "black": "matte black",
}
NAMED_COLORS = {
    "black": (25, 25, 25), "charcoal": (60, 60, 64), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "white": (245, 245, 240), "cream": (240, 230, 200), "beige": (215, 195, 160), "tan": (190, 150, 100),
    "brown": (110, 70, 40), "burgundy": (110, 20, 40), "red": (200, 30, 30), "coral": (240, 120, 100),
    "orange": (235, 130, 30), "mustard": (210, 170, 40), "yellow": (245, 215, 50), "olive": (110, 120, 40),
    "green": (40, 140, 60), "forest green": (30, 80, 45), "teal": (20, 120, 120), "turquoise": (50, 190, 190),
    "sky blue": (120, 180, 230), "blue": (40, 80, 200), "navy": (20, 30, 80), "purple": (110, 50, 150),
    "lavender": (180, 150, 220), "pink": (235, 120, 170), "magenta": (200, 30, 140),
}


def color_name(hex_color: str) -> str:
    if not hex_color or len(hex_color) != 7:
        return ""
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return min(NAMED_COLORS, key=lambda n: sum((a - b) ** 2 for a, b in zip(NAMED_COLORS[n], rgb)))


# ---------------------------------------------------------------- Claude: plan

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "room": {"type": "string"},
        "shelves": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "kind": {"type": "string", "enum": ["spine", "face_out", "stack"]},
                            },
                            "required": ["id", "kind"],
                            "additionalProperties": False,
                        },
                    },
                    "ornament": {"type": "string"},
                },
                "required": ["items", "ornament"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["room", "shelves"],
    "additionalProperties": False,
}

PLAN_SYSTEM = """You are an interior stylist arranging a real person's books on a bookcase for a photo that
will be their video-call background. An image model will paint the photo from your plan, and the book titles must
be legible, so every book you place must be one from the list (use its id), each at most once.

- Arrange the books over {shelves} shelves, grouped sensibly (by genre or colour) so the shelves look curated.
- Mark {face_out} of the most striking or recognisable books as "face_out" (cover facing forward), spread across
  different shelves. Optionally lay 2-3 books flat as a "stack" on one or two shelves. Everything else is "spine".
- Give each shelf one ornament with its position, e.g. "a small trailing pothos at the right end" or "a
  table lamp, glowing warmly, between the books". Vary them, in keeping with the theme: {ornaments}.
- room: one paragraph describing the room around the bookcase — walls, floor, light, and either side of it a
  lit lamp, real greenery and a piece of furniture. Keep the centre calm (a person will sit in front of it) and
  the light soft. {style}"""


def plan_scene(client, books: list[dict], shelves: int, face_out: int, theme) -> dict:
    listing = "\n".join(json.dumps(b, ensure_ascii=False) for b in books)
    style_text = (f"Theme: {theme.name}. Base the room on: {theme.room}." if theme.room
                  else "Choose a room style that suits this reader's taste.")
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        system=PLAN_SYSTEM.format(shelves=shelves, face_out=face_out, style=style_text, ornaments=theme.ornaments),
        messages=[{"role": "user", "content": f"Books ({len(books)}):\n{listing}"}],
    )
    if response.stop_reason == "refusal":
        raise SystemExit("Claude declined to plan this scene.")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


# ---------------------------------------------------------------- prompt

def build_prompt(plan: dict, by_id: dict, theme, finish: str | None, refs: list[str], feedback: str = "") -> str:
    bookcase = theme.bookcase + (f", in a {FINISH_TEXT[finish]} finish" if finish else "")
    lines = [
        "A photorealistic interior photograph used as a video-call background, eye level, 35mm lens, soft "
        f"depth of field. Look: {theme.photo}. Compose it for a 16:9 crop: keep the bookcase and everything "
        "important clear of the top and bottom 10% of the frame.",
        plan["room"],
        f"In the centre stands {bookcase}, with {len(plan['shelves'])} shelves, "
        "about half the frame wide. Its books are real and their spines must be legible: print every title "
        "and author EXACTLY as written below, in clear lettering, reading top to bottom on vertical spines. "
        "Do not add any other books with readable text; any filler books must have plain, untitled spines.",
    ]
    for n, shelf in enumerate(plan["shelves"], 1):
        where = "top" if n == 1 else "bottom" if n == len(plan["shelves"]) else f"#{n}"
        lines.append(f"\nShelf {n} ({where}), left to right:")
        for item in shelf["items"]:
            b = by_id.get(item["id"])
            if not b:
                continue
            look = ", ".join(x for x in (b["look"], f"{b['color']} cover" if b["color"] else "") if x)
            if item["kind"] == "face_out":
                ref = f" (use reference image {refs.index(item['id']) + 1} for the cover)" if item["id"] in refs else ""
                lines.append(f'- standing face-out with its cover facing forward: "{b["title"]}" by {b["author"]}{ref}')
            elif item["kind"] == "stack":
                lines.append(f'- lying flat in a small stack, spine facing out: "{b["title"]}" — {b["surname"]} ({look})')
            else:
                lines.append(f'- spine: "{b["title"]}" — {b["surname"]} ({look})')
        lines.append(f"- ornament: {shelf['ornament']}")
    lines.append("\nNo people, no logos, and no readable text other than the book titles and authors listed.")
    if feedback:
        lines.append("\nA previous attempt got these wrong — fix them this time:\n" + feedback)
    return "\n".join(lines)


# ---------------------------------------------------------------- image model

def paint(prompt: str, refs: list[Path], model: str, quality: str) -> Image.Image:
    from openai import OpenAI

    client = OpenAI()
    if refs:
        result = client.images.edit(
            model=model,
            image=[(p.name, p.read_bytes(), "image/jpeg") for p in refs],
            prompt=prompt,
            size=AI_SIZE,
            quality=quality,
        )
    else:
        result = client.images.generate(model=model, prompt=prompt, size=AI_SIZE, quality=quality)
    return Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json))).convert("RGB")


# ---------------------------------------------------------------- Claude: check

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string", "enum": ["correct", "minor_error", "wrong", "missing"]},
                    "seen_as": {"type": "string"},
                },
                "required": ["id", "status", "seen_as"],
                "additionalProperties": False,
            },
        },
        "invented": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["titles", "invented", "notes"],
    "additionalProperties": False,
}

CHECK_SYSTEM = """You proofread AI-generated photos of bookshelves. You get the image and the list of books that
were supposed to appear. Read every spine and cover you can see and, for each expected book, report:
correct = title clearly legible and spelled right; minor_error = recognisable but with a small typo or a dropped
word; wrong = garbled or a different title; missing = not visible. seen_as = what is actually printed ("" if
missing). List in `invented` any other readable titles on books that weren't requested. In `notes`, briefly
mention anything else that would look odd on a video call (warped books, floating objects, text on walls)."""


def check(client, img: Image.Image, expected: list[dict]) -> dict:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": CHECK_SCHEMA}},
        system=CHECK_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.standard_b64encode(buf.getvalue()).decode()}},
                {"type": "text", "text": "Expected books:\n" + "\n".join(
                    json.dumps({"id": b["id"], "title": b["title"], "author": b["author"]}, ensure_ascii=False)
                    for b in expected)},
            ],
        }],
    )
    if response.stop_reason == "refusal":
        return {"titles": [], "invented": [], "notes": "check declined"}
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def score(report: dict, n_expected: int) -> float:
    points = {"correct": 1.0, "minor_error": 0.5}
    got = sum(points.get(t["status"], 0) for t in report["titles"])
    return max(0.0, got - 0.25 * len(report["invented"])) / max(1, n_expected)


def feedback_text(report: dict, by_id: dict) -> str:
    out = []
    for t in report["titles"]:
        b = by_id.get(t["id"])
        if not b or t["status"] == "correct":
            continue
        if t["status"] == "missing":
            out.append(f'- "{b["title"]}" was missing')
        else:
            out.append(f'- "{b["title"]}" came out as "{t["seen_as"]}"')
    if report["invented"]:
        out.append("- these titles were invented and must not appear: " + "; ".join(report["invented"][:10]))
    if report["notes"]:
        out.append("- " + report["notes"])
    return "\n".join(out)


# ---------------------------------------------------------------- driver

def to_wallpaper(img: Image.Image) -> Image.Image:
    W, H = OUT_SIZE
    scale = W / img.width
    big = img.resize((W, round(img.height * scale)), Image.Resampling.LANCZOS)
    top = (big.height - H) // 2
    return big.crop((0, top, W, top + H))


def select_books(raw: list[dict], styles: dict, count: int, exclude: set[str]) -> list[dict]:
    rows = []
    for i, r in enumerate(raw):
        s = styles.get(r.get("asin"), {})
        if s.get("genre") in exclude:
            continue
        author = (r.get("authors") or [""])[0]
        rows.append({
            "id": r["asin"],
            "title": s.get("spine_title") or clean_title(r["title"]),
            "author": author,
            "surname": surname(author).upper() if author else "",
            "genre": s.get("genre", ""),
            "look": ", ".join(x for x in (BINDING_TEXT.get(s.get("binding"), ""),
                                          f"{TYPEFACE_TEXT[s['typeface']]} lettering" if s.get("typeface") in TYPEFACE_TEXT else "")
                              if x),
            "color": color_name(s.get("spine_color", "")),
            "_rank": (-s.get("notability", 3), i),
        })
    rows.sort(key=lambda r: r["_rank"])
    return [{k: v for k, v in r.items() if k != "_rank"} for r in rows[:count]]


def generate(
    raw: list[dict],
    styles: dict,
    covers_dir: Path,
    out_dir: Path,
    *,
    count: int,
    shelves: int,
    face_out: int,
    theme,
    finish: str | None,
    model: str,
    quality: str,
    attempts: int,
    good_enough: float,
    exclude: set[str],
    reuse_plan: bool,
) -> Image.Image:
    out_dir.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()
    books = select_books(raw, styles, count, exclude)
    by_id = {b["id"]: b for b in books}

    plan_path = out_dir / "plan.json"
    if reuse_plan and plan_path.exists():
        plan = json.loads(plan_path.read_text())
        print(f"Reusing plan {plan_path}")
    else:
        print(f"Planning a scene with {len(books)} books ({MODEL})...")
        plan = plan_scene(client, [{k: b[k] for k in ("id", "title", "author", "genre", "color")} for b in books],
                          shelves, face_out, theme)
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    print(f"Room: {plan['room']}")

    placed = [it["id"] for sh in plan["shelves"] for it in sh["items"] if it["id"] in by_id]
    expected = [by_id[i] for i in dict.fromkeys(placed)]
    refs = [it["id"] for sh in plan["shelves"] for it in sh["items"]
            if it["kind"] == "face_out" and (covers_dir / f"{it['id']}.jpg").exists()][:8]
    ref_paths = [covers_dir / f"{i}.jpg" for i in refs]

    best, best_score, feedback = None, -1.0, ""
    for n in range(1, attempts + 1):
        prompt = build_prompt(plan, by_id, theme, finish, refs, feedback)
        (out_dir / f"attempt-{n}.prompt.txt").write_text(prompt)
        print(f"Attempt {n}/{attempts}: painting with {model} ({len(expected)} books, {len(refs)} cover references)...")
        img = paint(prompt, ref_paths, model, quality)
        img.save(out_dir / f"attempt-{n}.png")
        print("  checking titles with Claude...")
        report = check(client, img, expected)
        (out_dir / f"attempt-{n}.check.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        s = score(report, len(expected))
        ok = sum(t["status"] == "correct" for t in report["titles"])
        print(f"  {ok}/{len(expected)} titles correct, {len(report['invented'])} invented -> score {s:.0%}")
        if s > best_score:
            best, best_score = img, s
        if s >= good_enough:
            break
        feedback = feedback_text(report, by_id)
    print(f"Best attempt scored {best_score:.0%}; all attempts are in {out_dir}")
    return to_wallpaper(best)
