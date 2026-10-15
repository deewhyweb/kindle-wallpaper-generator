"""kindle-wallpaper: fetch your Kindle library and render it as a bookcase."""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

DEMO_BOOKS = [
    ("Pride and Prejudice", "Jane Austen"), ("Moby-Dick", "Herman Melville"),
    ("The Great Gatsby", "F. Scott Fitzgerald"), ("Dune", "Frank Herbert"),
    ("The Hobbit", "J. R. R. Tolkien"), ("Neuromancer", "William Gibson"),
    ("Project Hail Mary", "Andy Weir"), ("The Martian", "Andy Weir"),
    ("Thinking, Fast and Slow", "Daniel Kahneman"), ("Sapiens", "Yuval Noah Harari"),
    ("The Pragmatic Programmer", "David Thomas"), ("Clean Code", "Robert C. Martin"),
    ("Designing Data-Intensive Applications", "Martin Kleppmann"),
    ("The Phoenix Project", "Gene Kim"), ("Accelerate", "Nicole Forsgren"),
    ("Frankenstein", "Mary Shelley"), ("Dracula", "Bram Stoker"),
    ("Jane Eyre", "Charlotte Brontë"), ("Wuthering Heights", "Emily Brontë"),
    ("The Left Hand of Darkness", "Ursula K. Le Guin"), ("A Wizard of Earthsea", "Ursula K. Le Guin"),
    ("Foundation", "Isaac Asimov"), ("I, Robot", "Isaac Asimov"),
    ("Snow Crash", "Neal Stephenson"), ("Cryptonomicon", "Neal Stephenson"),
    ("The Name of the Wind", "Patrick Rothfuss"), ("Mistborn: The Final Empire", "Brandon Sanderson"),
    ("The Way of Kings (The Stormlight Archive, Book 1)", "Brandon Sanderson"),
    ("Educated: A Memoir", "Tara Westover"), ("Atomic Habits", "James Clear"),
    ("Deep Work", "Cal Newport"), ("The Mythical Man-Month", "Frederick P. Brooks Jr."),
    ("Gödel, Escher, Bach", "Douglas Hofstadter"), ("The Code Book", "Simon Singh"),
    ("A Brief History of Time", "Stephen Hawking"), ("Cosmos", "Carl Sagan"),
    ("The Road", "Cormac McCarthy"), ("Blood Meridian", "Cormac McCarthy"),
    ("Station Eleven", "Emily St. John Mandel"), ("Klara and the Sun", "Kazuo Ishiguro"),
    ("Never Let Me Go", "Kazuo Ishiguro"), ("The Remains of the Day", "Kazuo Ishiguro"),
    ("1984", "George Orwell"), ("Animal Farm", "George Orwell"),
    ("Brave New World", "Aldous Huxley"), ("Fahrenheit 451", "Ray Bradbury"),
    ("The Hitchhiker's Guide to the Galaxy", "Douglas Adams"), ("Good Omens", "Terry Pratchett"),
    ("Small Gods", "Terry Pratchett"), ("Guards! Guards!", "Terry Pratchett"),
    ("The Three-Body Problem", "Cixin Liu"), ("Recursion", "Blake Crouch"),
    ("Dark Matter", "Blake Crouch"), ("Gone Girl", "Gillian Flynn"),
    ("The Girl with the Dragon Tattoo", "Stieg Larsson"), ("The Da Vinci Code", "Dan Brown"),
    ("Kitchen Confidential", "Anthony Bourdain"), ("Born a Crime", "Trevor Noah"),
    ("The Body Keeps the Score", "Bessel van der Kolk"), ("Range", "David Epstein"),
    ("Outliers", "Malcolm Gladwell"), ("The Tipping Point", "Malcolm Gladwell"),
    ("Freakonomics", "Steven D. Levitt"), ("The Lean Startup", "Eric Ries"),
    ("Zero to One", "Peter Thiel"), ("Shoe Dog", "Phil Knight"),
    ("Becoming", "Michelle Obama"), ("Leonardo da Vinci", "Walter Isaacson"),
    ("Steve Jobs", "Walter Isaacson"), ("The Wright Brothers", "David McCullough"),
    ("Team of Rivals", "Doris Kearns Goodwin"), ("Guns, Germs, and Steel", "Jared Diamond"),
    ("The Silmarillion", "J. R. R. Tolkien"), ("The Fellowship of the Ring", "J. R. R. Tolkien"),
    ("Circe", "Madeline Miller"), ("The Song of Achilles", "Madeline Miller"),
    ("Piranesi", "Susanna Clarke"), ("Jonathan Strange & Mr Norrell", "Susanna Clarke"),
    ("The Night Circus", "Erin Morgenstern"), ("American Gods", "Neil Gaiman"),
    ("Anansi Boys", "Neil Gaiman"), ("Neverwhere", "Neil Gaiman"),
    ("Hyperion", "Dan Simmons"), ("Ender's Game", "Orson Scott Card"),
    ("Red Rising", "Pierce Brown"), ("Leviathan Wakes", "James S. A. Corey"),
    ("Children of Time", "Adrian Tchaikovsky"), ("Old Man's War", "John Scalzi"),
    ("Annihilation", "Jeff VanderMeer"), ("The Fifth Season", "N. K. Jemisin"),
    ("Kindred", "Octavia E. Butler"), ("Parable of the Sower", "Octavia E. Butler"),
    ("Beloved", "Toni Morrison"), ("The Color Purple", "Alice Walker"),
    ("To Kill a Mockingbird", "Harper Lee"), ("Of Mice and Men", "John Steinbeck"),
    ("East of Eden", "John Steinbeck"), ("The Grapes of Wrath", "John Steinbeck"),
    ("Slaughterhouse-Five", "Kurt Vonnegut"), ("Cat's Cradle", "Kurt Vonnegut"),
    ("Catch-22", "Joseph Heller"), ("The Catcher in the Rye", "J. D. Salinger"),
]


def cmd_fetch(args) -> None:
    from .fetch import fetch

    fetch(Path(args.data), args.domain, Path(args.profile), args.include_samples)


def _load(args) -> tuple[list[dict], Path | None, dict | None]:
    data = Path(args.data)
    raw = json.loads((data / "books.json").read_text())
    styles_path = data / "styles.json"
    styles = None
    if styles_path.exists() and not args.no_styles:
        styles = json.loads(styles_path.read_text())
    return raw, data / "covers", styles


def _theme(args):
    from .themes import resolve

    return resolve(args.theme, Path(getattr(args, "data", "data")))


def _bookcase(args, raw, covers, styles, size, out, decor=None, theme=None):
    from .render import render

    finish = args.finish or (theme or _theme(args)).finish
    if args.exclude_genres:
        if not styles:
            raise SystemExit("--exclude-genres needs Claude's styling; run `kindle-wallpaper curate` first.")
        skip = {g.strip() for g in args.exclude_genres.split(",")}
        raw = [b for b in raw if styles.get(b.get("asin"), {}).get("genre") not in skip]
    if args.limit:
        raw = raw[: args.limit]
    sort = args.sort or ("genre" if styles else "author")
    return render(
        raw, covers, out, size=size, sort=sort, shelves=args.shelves,
        face_out_every=args.face_out_every, seed=args.seed, finish=finish,
        styles=styles, max_shelves=args.max_shelves, decor=decor,
    )


def cmd_curate(args) -> None:
    from .curate import curate

    curate(Path(args.data), force=args.force)


def cmd_render(args, raw: list[dict] | None = None) -> None:
    covers = styles = None
    if raw is None:
        raw, covers, styles = _load(args)
    w, h = (int(v) for v in args.size.lower().split("x"))
    _bookcase(args, raw, covers, styles, (w, h), Path(args.out))


def cmd_room(args) -> None:
    from .render import save
    from .room import DECOR_PROMPT, PROMPT, bookcase_box, make_room_wallpaper

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY to generate rooms (platform.openai.com/api-keys).")
    raw, covers, styles = _load(args)
    data = Path(args.data)
    theme = _theme(args)
    if theme.room:
        room = theme.room
    else:  # auto: Claude designs a room from your reading taste
        cache = data / "room_prompt.txt"
        if cache.exists() and not args.regenerate:
            room = cache.read_text().strip()
        else:
            if not styles:
                raise SystemExit("--theme auto needs Claude's styling; run `kindle-wallpaper curate` first.")
            from .curate import room_prompt

            room = room_prompt(styles, raw)
            cache.write_text(room)
        print(f"Room: {room}")
    box = bookcase_box(args.bookcase_width)
    slots = None if args.no_decor else []
    bookcase = _bookcase(args, raw, covers, styles, box[2:], None, decor=slots, theme=theme)
    decor = "" if args.no_decor else DECOR_PROMPT.format(ornaments=theme.ornaments)
    prompt = PROMPT.format(room=room, decor=decor, photo=theme.photo)
    final = make_room_wallpaper(
        bookcase, slots or [], box, prompt, data / "rooms", args.image_model, args.quality,
        args.finish or theme.finish, regenerate=args.regenerate,
    )
    save(final, Path(args.out))


def cmd_generate(args) -> None:
    from .generate import generate
    from .render import save

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY to generate images (platform.openai.com/api-keys).")
    data = Path(args.data)
    raw = json.loads((data / "books.json").read_text())
    styles_path = data / "styles.json"
    styles = json.loads(styles_path.read_text()) if styles_path.exists() else {}
    if not styles:
        print("Tip: run `kindle-wallpaper curate` first so Claude can pick your most notable books.")
    theme = _theme(args)
    img = generate(
        raw, styles, data / "covers", data / "generated",
        count=args.books, shelves=args.shelves, face_out=args.face_out, theme=theme, finish=args.finish,
        model=args.image_model, quality=args.quality, attempts=args.attempts, good_enough=args.good_enough,
        exclude={g.strip() for g in (args.exclude_genres or "").split(",") if g.strip()},
        reuse_plan=args.reuse_plan,
    )
    save(img, Path(args.out))


def cmd_demo(args) -> None:
    rng = random.Random(args.seed)
    books = DEMO_BOOKS[:]
    rng.shuffle(books)
    raw = [{"asin": f"demo{i}", "title": t, "authors": [a]} for i, (t, a) in enumerate(books[: args.count])]
    cmd_render(args, raw)


def main() -> None:
    ap = argparse.ArgumentParser(prog="kindle-wallpaper", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="log in (in a browser window) and download your Kindle library")
    f.add_argument("--data", default="data", help="where to store books.json and covers/ (default: data)")
    f.add_argument("--domain", default="amazon.com", help="Amazon domain, e.g. amazon.co.uk (default: amazon.com)")
    f.add_argument("--profile", default=".browser-profile", help="browser profile dir that keeps you logged in")
    f.add_argument("--include-samples", action="store_true", help="include free samples")
    f.set_defaults(func=cmd_fetch)

    from .render import FINISHES
    from .themes import names as theme_names

    theme_help = (f"scene theme: one of {', '.join(theme_names())}, 'auto', or your own words "
                  "(e.g. \"1990s college dorm\")")

    c = sub.add_parser("curate", help="have Claude style and rank your books (needs ANTHROPIC_API_KEY)")
    c.add_argument("--data", default="data")
    c.add_argument("--force", action="store_true", help="re-style books that were already styled")
    c.set_defaults(func=cmd_curate)

    def render_opts(p, max_shelves=5):
        p.add_argument("--out", default="bookshelf.jpg", help="output image (default: bookshelf.jpg)")
        p.add_argument("--size", default="1920x1080", help="image size WxH (default: 1920x1080)")
        p.add_argument("--sort", choices=["genre", "author", "title", "recent", "color", "random"],
                       help="shelf order (default: genre if curated, else author)")
        p.add_argument("--theme", default="cozy-study", help=theme_help)
        p.add_argument("--finish", choices=sorted(FINISHES), help="bookcase wood finish (default: set by --theme)")
        p.add_argument("--shelves", type=int, help="number of shelves (default: auto)")
        p.add_argument("--max-shelves", type=int, default=max_shelves,
                       help=f"most shelves to use before dropping less notable books (default: {max_shelves})")
        p.add_argument("--no-styles", action="store_true", help="ignore Claude's styling in styles.json")
        p.add_argument("--exclude-genres", help="comma-separated genres to leave off, e.g. children_ya,comics")
        p.add_argument("--limit", type=int, help="only use the first N books (after fetch order)")
        p.add_argument("--face-out-every", type=int, default=14, help="show every Nth cover face-out (0 = never)")
        p.add_argument("--seed", type=int, default=7, help="change for a different random arrangement")

    r = sub.add_parser("render", help="render the bookcase image from fetched data")
    r.add_argument("--data", default="data")
    render_opts(r)
    r.set_defaults(func=cmd_render)

    rm = sub.add_parser("room", help="put the bookcase in an AI-generated room (needs OPENAI_API_KEY)")
    rm.add_argument("--data", default="data")
    render_opts(rm, max_shelves=4)
    rm.add_argument("--image-model", default="gpt-image-1", help="OpenAI image model (default: gpt-image-1)")
    rm.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    rm.add_argument("--bookcase-width", type=float, default=0.5,
                    help="bookcase width as a fraction of the frame; smaller shows more room (default: 0.5)")
    rm.add_argument("--no-decor", action="store_true", help="fill the shelves with books only, no ornaments")
    rm.add_argument("--regenerate", action="store_true", help="generate a new room instead of reusing the cached one")
    rm.set_defaults(func=cmd_room, out="bookshelf_room.jpg")

    g = sub.add_parser("generate", help="have the image model paint the whole scene, books included "
                                        "(needs OPENAI_API_KEY and ANTHROPIC_API_KEY)")
    g.add_argument("--data", default="data")
    g.add_argument("--out", default="bookshelf_generated.jpg")
    g.add_argument("--books", type=int, default=36, help="how many books to show (default: 36; more = smaller, "
                                                          "less reliable titles)")
    g.add_argument("--shelves", type=int, default=4)
    g.add_argument("--face-out", type=int, default=4, help="books shown cover-forward, using their real covers")
    g.add_argument("--theme", default="auto", help=theme_help + "; 'auto' lets Claude choose")
    g.add_argument("--finish", choices=sorted(FINISHES), help="override the bookcase wood finish")
    g.add_argument("--exclude-genres", help="comma-separated genres to leave off, e.g. children_ya,comics")
    g.add_argument("--image-model", default="gpt-image-2",
                   help="OpenAI image model (default: gpt-image-2, which renders text far better than gpt-image-1)")
    g.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    g.add_argument("--attempts", type=int, default=3, help="max images to generate while chasing correct titles")
    g.add_argument("--good-enough", type=float, default=0.9, help="stop early once this share of titles is right")
    g.add_argument("--reuse-plan", action="store_true", help="keep the last shelf plan, just repaint")
    g.set_defaults(func=cmd_generate)

    d = sub.add_parser("demo", help="render with a built-in sample library (no login needed)")
    d.add_argument("--count", type=int, default=80)
    render_opts(d)
    d.set_defaults(func=cmd_demo, out="demo.jpg", no_styles=True, exclude_genres=None)

    args = ap.parse_args()
    try:
        args.func(args)
    except TypeError as e:  # raised by the Anthropic client when it finds no credentials
        if "authentication" not in str(e):
            raise
        raise SystemExit("No Anthropic credentials found. Set ANTHROPIC_API_KEY (console.anthropic.com).")


if __name__ == "__main__":
    main()
