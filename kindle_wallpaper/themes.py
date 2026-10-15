"""Scene themes: the overall look of the room, the bookcase, its ornaments and the photo.

Use a preset name (`--theme 70s`) or describe one in your own words
(`--theme "1990s college dorm"`). Free-text themes are expanded by Claude into the
same fields as a preset, once, and cached in data/themes/.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .render import FINISHES


@dataclass(frozen=True)
class Theme:
    name: str
    finish: str      # wood finish for the code-drawn bookcase (render/room)
    room: str        # walls, floor, light, furniture, lamps and plants around the bookcase
    bookcase: str    # what the bookcase itself looks like (generate)
    ornaments: str   # the kind of objects that sit on the shelves
    photo: str       # photographic look


PRESETS = {
    "modern": Theme(
        "modern", "white",
        "a bright contemporary living room: clean lines, warm white walls, a large window with sheer curtains, "
        "pale wood floor with a textured rug, a sculptural arc floor lamp, an olive tree in a concrete planter, "
        "a low boucle armchair",
        "sleek built-in shelving with thin white shelves and a soft hidden LED strip under each shelf",
        "matte ceramic vases, a small abstract sculpture, a minimalist table lamp, a trailing plant in a white pot",
        "crisp, bright, editorial interior-magazine photography",
    ),
    "victorian": Theme(
        "victorian", "mahogany",
        "a Victorian study: dark wood panelling, a deep red Persian rug, a tufted leather chesterfield wingback, "
        "a green glass banker's lamp, brass candlesticks, a potted aspidistra and a palm in a jardinière, heavy "
        "velvet drapes",
        "an ornate carved mahogany bookcase with a decorative cornice and fluted pilasters",
        "a brass globe, a mantel clock, a candlestick, a small marble bust, a framed sepia photograph",
        "rich, warm, low-key lighting like an old master painting",
    ),
    "70s": Theme(
        "70s", "walnut",
        "a 1970s living room: wood-panelled walls, a burnt orange and avocado green palette, a shag rug, "
        "macramé plant hangers with spider plants, a glowing mushroom lamp, a rattan peacock chair",
        "a teak wall unit with chunky shelves",
        "a macramé plant hanger, a lava lamp, a ceramic owl, a glass terrarium, a few vinyl records",
        "a 1970s film photograph: warm, slightly faded Kodachrome colours with subtle grain (titles still sharp)",
    ),
    "mid-century": Theme(
        "mid-century", "walnut",
        "a mid-century modern den: walnut panelling, a sunburst clock, an Eames-style lounge chair, a ceramic "
        "table lamp, a mustard accent wall, a rubber plant, warm late-afternoon light",
        "a walnut mid-century bookcase on tapered legs",
        "a teak bird figurine, a Scandinavian glass vase, a small brass lamp, a snake plant in a ceramic pot",
        "warm, softly saturated 1960s-inspired interior photography",
    ),
    "art-deco": Theme(
        "art-deco", "black",
        "a 1920s Art Deco lounge: deep emerald walls, geometric brass details, a velvet club chair, a fan-shaped "
        "glass sconce, a tall palm in a lacquered planter, a herringbone parquet floor",
        "a black lacquered bookcase with brass trim and stepped geometric edges",
        "a chrome and glass lamp, a geometric brass bookend, a crystal decanter, a small bronze figurine",
        "glamorous, moody, high-contrast lighting",
    ),
    "80s": Theme(
        "80s", "white",
        "an 1980s Memphis-style living room: pastel pink and mint walls with bold squiggle accents, a neon sign "
        "glow (no readable words), a glossy black lacquered side table, a potted palm, a chunky halogen floor lamp",
        "a glossy white laminate bookcase with colourful geometric accents",
        "a cassette tape stack, a lava lamp, a pastel ceramic vase, a cactus, a rubik's cube",
        "vibrant, saturated 1980s catalogue photography",
    ),
    "cottage": Theme(
        "cottage", "oak",
        "a cosy English cottage sitting room: low beamed ceiling, whitewashed walls, a stone fireplace, a "
        "chintz armchair with a knitted throw, a brass reading lamp, potted geraniums and trailing ivy on the "
        "windowsill",
        "a painted, slightly weathered country dresser-style bookcase",
        "a jug of wildflowers, a teacup and saucer, a candle in a brass holder, a small ceramic hen",
        "soft, warm, morning-light photography",
    ),
    "industrial": Theme(
        "industrial", "black",
        "an industrial loft: exposed red brick, black steel-framed windows, polished concrete floor, a leather "
        "sofa, an Edison-bulb pendant and a black tripod floor lamp, a large fiddle-leaf fig",
        "black steel pipe-and-reclaimed-wood shelving",
        "an Edison-bulb desk lamp, a concrete planter with a succulent, a vintage camera, metal bookends",
        "moody urban interior photography with soft window light",
    ),
    "japandi": Theme(
        "japandi", "oak",
        "a calm Japandi room: warm plaster walls, pale oak floor, a low linen sofa, a paper lantern floor lamp, "
        "a bonsai and a tall bamboo in stoneware pots, minimal decor",
        "a pale oak bookcase with simple, slatted sides",
        "a stoneware vase with a single branch, a small bonsai, an incense holder, a paper lamp",
        "serene, soft, diffuse natural light",
    ),
    "scandinavian": Theme(
        "scandinavian", "white",
        "a calm Scandinavian living room: pale oak floor, soft white walls, a linen armchair with a sheepskin, "
        "a ceramic vase of dried flowers on a low sideboard, a white pendant lamp, a monstera, diffuse daylight",
        "a simple white bookcase with clean lines",
        "dried flowers in a ceramic vase, candles, a wooden bird, a small potted plant",
        "bright, airy, natural-light photography",
    ),
    "cozy-study": Theme(
        "cozy-study", "walnut",
        "a cozy home study: deep green painted walls, warm lamplight, a worn leather armchair, a brass floor "
        "lamp, a potted fiddle-leaf fig, a Persian rug on dark wooden floorboards",
        "a solid dark-wood bookcase",
        "a small brass lamp, a trailing pothos, a framed photo, a candle, a ceramic jug",
        "warm, intimate evening photography",
    ),
    "library": Theme(
        "library", "mahogany",
        "a grand old private library: dark wood panelling, a rolling brass ladder, a green banker's lamp on a "
        "side table, a tall arched window with soft afternoon light, a large potted palm, rich carpet",
        "a tall, built-in dark wood library bookcase with crown moulding",
        "a brass globe, an hourglass, a small marble bust, a candlestick",
        "rich, warm, atmospheric photography",
    ),
    "dark-academia": Theme(
        "dark-academia", "mahogany",
        "a moody dark-academia study: candlelit sconces, oxblood walls, a globe and old maps on a writing desk, "
        "heavy velvet curtains, a marble bust, ivy in an old terracotta pot",
        "an old dark oak bookcase, slightly worn",
        "candles in brass holders, a skull-shaped bookend, dried roses, an antique magnifying glass",
        "moody, candle-lit, low-key photography",
    ),
}
ALIASES = {"old-fashioned": "victorian", "traditional": "victorian", "seventies": "70s", "1970s": "70s",
           "eighties": "80s", "1980s": "80s", "1920s": "art-deco", "60s": "mid-century", "1960s": "mid-century",
           "50s": "mid-century", "contemporary": "modern", "minimal": "modern", "rustic": "cottage"}

EXPAND_SCHEMA = {
    "type": "object",
    "properties": {
        "finish": {"type": "string", "enum": sorted(FINISHES)},
        "room": {"type": "string"},
        "bookcase": {"type": "string"},
        "ornaments": {"type": "string"},
        "photo": {"type": "string"},
    },
    "required": ["finish", "room", "bookcase", "ornaments", "photo"],
    "additionalProperties": False,
}

EXPAND_SYSTEM = """You are an interior stylist. Turn a short theme into a brief for an image model that will
paint a room with a bookcase, as a video-call background. Match the examples' length and specificity.
- finish: the closest wood finish for a simple illustrated bookcase.
- room: walls, floor, light, and either side of the bookcase a lit lamp, real greenery and a piece of furniture.
  Keep the light soft and flattering.
- bookcase: what the bookcase itself looks like in this theme.
- ornaments: 4-5 small objects that suit the theme and fit on a shelf.
- photo: the photographic look, in one line. Book titles must stay sharp and readable.

Example for "70s":
""" + json.dumps({k: v for k, v in asdict(PRESETS["70s"]).items() if k != "name"}, indent=2)


AUTO = Theme(
    "auto", "walnut", "", "a solid wooden bookcase",
    "small potted plants, a little table lamp, ceramics, a framed photo, candles",
    "warm, natural interior photography",
)


def names() -> list[str]:
    return sorted(PRESETS)


def resolve(text: str, data_dir: Path) -> Theme:
    """A preset by name, or a free-text theme expanded (and cached) by Claude."""
    key = text.strip().lower()
    key = ALIASES.get(key, key)
    if key == "auto":
        return AUTO
    if key in PRESETS:
        return PRESETS[key]
    cache = data_dir / "themes" / (re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:60] + ".json")
    if cache.exists():
        return Theme(**json.loads(cache.read_text()))

    import anthropic

    from .curate import MODEL

    print(f'Asking Claude to design the "{text}" theme...')
    response = anthropic.Anthropic().beta.messages.create(
        model=MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": EXPAND_SCHEMA}},
        system=EXPAND_SYSTEM,
        messages=[{"role": "user", "content": f"Theme: {text}"}],
    )
    if response.stop_reason == "refusal":
        raise SystemExit(f'Claude declined to design the theme "{text}"; try a preset: {", ".join(names())}')
    theme = Theme(name=text, **json.loads(next(b.text for b in response.content if b.type == "text")))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(asdict(theme), indent=2, ensure_ascii=False))
    return theme
