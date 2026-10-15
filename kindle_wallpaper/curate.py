"""Use Claude to style and rank books for the bookcase.

For each book Claude picks a genre, a binding style, a typeface, a spine colour, a
short spine title, and a "notability" score (how recognisable / interesting it is
on a shelf behind you). Results are cached in data/styles.json keyed by ASIN, so
re-running only sends books Claude hasn't seen yet.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
CHUNK = 60

GENRES = [
    "classics", "literary_fiction", "mystery_crime", "thriller", "sci_fi", "fantasy",
    "horror", "romance", "humor", "history", "biography_memoir", "science", "technology",
    "business", "self_help", "philosophy_religion", "politics_society", "essays",
    "poetry", "children_ya", "comics", "food_travel", "reference", "other",
]
BINDINGS = ["leather_gilt", "cloth_classic", "modern_hardcover", "paperback", "technical", "pulp"]
TYPEFACES = ["classic_serif", "modern_serif", "bold_sans", "condensed_sans", "display"]

BOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "genre": {"type": "string", "enum": GENRES},
        "binding": {"type": "string", "enum": BINDINGS},
        "typeface": {"type": "string", "enum": TYPEFACES},
        "spine_color": {"type": "string", "description": "#RRGGBB"},
        "spine_title": {"type": "string"},
        "notability": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    },
    "required": ["id", "genre", "binding", "typeface", "spine_color", "spine_title", "notability"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"books": {"type": "array", "items": BOOK_SCHEMA}},
    "required": ["books"],
    "additionalProperties": False,
}

SYSTEM = """You are a book designer styling spines for an illustrated bookcase that will be a video-call background.

For every book you are given, return one entry with the same id:
- genre: the best-fitting genre from the allowed list.
- binding: how this book would look as a physical object on a tasteful shelf.
  leather_gilt = antique/collectible classics; cloth_classic = older literary hardcovers with simple bands;
  modern_hardcover = recent bestsellers and non-fiction with dust jackets; paperback = genre fiction,
  series mysteries, light reads; technical = programming/engineering manuals; pulp = vintage-style crime/sci-fi.
- typeface: the lettering style a designer would use on that spine.
- spine_color: the colour the real edition's cover/spine is known for if you know it, otherwise a colour
  that fits the genre and binding. Format #RRGGBB.
- spine_title: the title as it would be printed on the spine — drop series names, "Book 3", subtitles and
  edition notes. Keep it short (ideally under 30 characters) without changing the title's meaning.
- notability: 5 = instantly recognisable classic or major bestseller that makes a good impression on a call;
  3 = solid, known within its genre; 1 = obscure, a free/promo title, a sample, a manual or reference
  document nobody would display.

Judge each book on its own merits; keep spine_title faithful to the real title."""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _style_chunk(client: anthropic.Anthropic, chunk: list[dict]) -> list[dict]:
    lines = "\n".join(
        json.dumps({"id": b["asin"], "title": b["title"], "authors": b.get("authors", [])}, ensure_ascii=False)
        for b in chunk
    )
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Style these {len(chunk)} books:\n{lines}"}],
    )
    if response.stop_reason == "max_tokens" and len(chunk) > 1:
        half = len(chunk) // 2
        return _style_chunk(client, chunk[:half]) + _style_chunk(client, chunk[half:])
    if response.stop_reason == "refusal":
        print(f"  Claude declined a chunk of {len(chunk)} books; they will use default styling.")
        return []
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["books"]


def _valid_hex(c: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", c or ""))


def curate(data_dir: Path, force: bool = False, workers: int = 4) -> Path:
    books = json.loads((data_dir / "books.json").read_text())
    out = data_dir / "styles.json"
    styles: dict[str, dict] = {} if force or not out.exists() else json.loads(out.read_text())

    todo = [b for b in books if b.get("asin") and b["asin"] not in styles]
    if not todo:
        print(f"All {len(books)} books already styled ({out}). Use --force to redo.")
        return out

    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    print(f"Styling {len(todo)} books with {MODEL} in {len(chunks)} requests...")
    client = _client()
    wanted = {b["asin"] for b in todo}

    def run(chunk):
        try:
            return _style_chunk(client, chunk)
        except anthropic.APIStatusError as e:
            print(f"  request failed ({e.status_code}): {e.message}")
            return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, result in enumerate(pool.map(run, chunks), 1):
            for s in result:
                if s["id"] in wanted:
                    if not _valid_hex(s["spine_color"]):
                        s["spine_color"] = ""
                    styles[s.pop("id")] = s
            out.write_text(json.dumps(styles, indent=2, ensure_ascii=False))  # save progress as we go
            print(f"  {i}/{len(chunks)} done")

    genres = Counter(s["genre"] for s in styles.values())
    print(f"Saved styles for {len(styles)} books to {out}")
    print("Top genres: " + ", ".join(f"{g} ({n})" for g, n in genres.most_common(6)))
    return out


ROOM_SYSTEM = """You write prompts for an image model that will paint a room around an existing bookcase.
The bookcase is already drawn in the centre of the frame and must not be described or changed — you only
describe the room around it: walls, flooring, lighting, furniture and objects to the left and right, and the
mood. Match the room to the owner's reading taste. Keep the space behind where a person sits (the centre)
calm, and the lighting soft and warm enough for a video call. Reply with a single paragraph under 120 words,
no preamble."""


def room_prompt(styles: dict[str, dict], books: list[dict]) -> str:
    """Ask Claude for a room description tailored to this library."""
    genres = Counter(s["genre"] for s in styles.values()).most_common(8)
    by_asin = {b["asin"]: b for b in books}
    top = sorted(styles.items(), key=lambda kv: -kv[1]["notability"])[:25]
    titles = [by_asin[a]["title"] for a, _ in top if a in by_asin]
    response = _client().beta.messages.create(
        model=MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=ROOM_SYSTEM,
        messages=[{
            "role": "user",
            "content": "Genre mix: " + ", ".join(f"{g} ({n})" for g, n in genres)
            + "\nSome favourite books: " + "; ".join(titles),
        }],
    )
    return next(b.text for b in response.content if b.type == "text").strip()
