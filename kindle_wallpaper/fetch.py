"""Fetch your Kindle library via a real, visible browser session.

You log in yourself in the browser window (password, 2FA, captcha -- all handled
by Amazon's own page). The session is kept in a local browser profile so you only
need to log in once. Nothing here ever sees your credentials.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

# Same JSON endpoint the Kindle Cloud Reader library page uses.
SEARCH_JS = """
async ({querySize, maxPages}) => {
  const items = [];
  let token = null;
  for (let i = 0; i < maxPages; i++) {
    const params = new URLSearchParams({
      query: '', libraryType: 'BOOKS', sortType: 'recency', querySize: String(querySize),
    });
    if (token) params.set('paginationToken', token);
    const resp = await fetch('/kindle-library/search?' + params, {
      credentials: 'include', headers: {'Accept': 'application/json'},
    });
    if (!resp.ok) throw new Error('library search returned HTTP ' + resp.status);
    const data = await resp.json();
    items.push(...(data.itemsList || []));
    token = data.paginationToken;
    if (!token) break;
  }
  return items;
}
"""

# Fallback: scrape the rendered library grid if the JSON endpoint changes.
SCRAPE_JS = """
() => Array.from(document.querySelectorAll('#cover li')).map(li => {
  const titleEl = li.querySelector('[id^="title-"]');
  const authorEl = li.querySelector('[id^="author-"]');
  const img = li.querySelector('img');
  return {
    asin: titleEl ? titleEl.id.replace(/^title-/, '') : (img && img.id) || '',
    title: titleEl ? titleEl.innerText.trim() : (img && img.alt) || '',
    authors: authorEl ? [authorEl.innerText.trim()] : [],
    productUrl: img ? img.src : '',
  };
})
"""


def _flip_name(name: str) -> str:
    """'Tolkien, J. R. R.' -> 'J. R. R. Tolkien'."""
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return name.strip()


def normalize(item: dict) -> dict:
    authors: list[str] = []
    for raw in item.get("authors") or []:
        for part in str(raw).split(":"):
            if part.strip():
                authors.append(_flip_name(part))
    return {
        "asin": item.get("asin", ""),
        "title": (item.get("title") or "").strip(),
        "authors": authors,
        "cover_url": item.get("productUrl") or "",
        "origin": item.get("originType", ""),
    }


def _wait_for_library(page: Page, base: str, timeout_s: int = 600) -> None:
    library_url = base + "/kindle-library"
    page.goto(library_url)
    deadline = time.time() + timeout_s
    prompted = False
    while time.time() < deadline:
        url = page.url
        if url.startswith(library_url):
            page.wait_for_load_state("networkidle")
            return
        if "signin" in url or "/ap/" in url:
            if not prompted:
                print("Please log in to Amazon in the browser window (waiting up to 10 min)...")
                prompted = True
        elif url.startswith(base):
            # Logged in but landed somewhere else (e.g. the reader landing page).
            page.goto(library_url)
        page.wait_for_timeout(1000)
    raise TimeoutError("Timed out waiting for login to the Kindle library.")


def _scrape_by_scrolling(page: Page) -> list[dict]:
    stable, last = 0, -1
    while stable < 3:
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(1500)
        count = page.evaluate("document.querySelectorAll('#cover li').length")
        stable = stable + 1 if count == last else 0
        last = count
    return page.evaluate(SCRAPE_JS)


def _launch(p, profile_dir: Path) -> BrowserContext:
    kwargs = dict(user_data_dir=str(profile_dir), headless=False, viewport={"width": 1280, "height": 900})
    try:
        # Prefer the locally installed Chrome; Amazon is friendlier to it.
        return p.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception:
        return p.chromium.launch_persistent_context(**kwargs)


def _hires(url: str) -> str:
    # Amazon image URLs carry a size token like '._SY400_.jpg'; ask for a bigger one.
    return re.sub(r"\._[^/]*?_\.(jpg|jpeg|png)$", r"._SY600_.\1", url)


def _download(url: str, dest: Path) -> bool:
    for candidate in dict.fromkeys([_hires(url), url]):
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                dest.write_bytes(resp.read())
            return True
        except Exception:
            continue
    return False


def download_covers(books: list[dict], covers_dir: Path) -> None:
    covers_dir.mkdir(parents=True, exist_ok=True)
    todo = [b for b in books if b["cover_url"] and b["asin"] and not (covers_dir / f"{b['asin']}.jpg").exists()]

    def work(book: dict) -> bool:
        return _download(book["cover_url"], covers_dir / f"{book['asin']}.jpg")

    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = sum(pool.map(work, todo))
    print(f"Downloaded {ok}/{len(todo)} new covers into {covers_dir}")


def fetch(data_dir: Path, domain: str, profile_dir: Path, include_samples: bool) -> Path:
    base = f"https://read.{domain}"
    data_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = _launch(p, profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        _wait_for_library(page, base)
        try:
            items = page.evaluate(SEARCH_JS, {"querySize": 50, "maxPages": 200})
        except Exception as exc:
            print(f"Library API failed ({exc}); falling back to scraping the page...")
            items = _scrape_by_scrolling(page)
        context.close()

    books = [normalize(i) for i in items]
    books = [b for b in books if b["title"]]
    if not include_samples:
        books = [b for b in books if b["origin"].upper() != "SAMPLE"]
    # De-duplicate by ASIN, keeping first (most recent) occurrence.
    seen: set[str] = set()
    books = [b for b in books if not ((k := b["asin"] or b["title"]) in seen or seen.add(k))]

    out = data_dir / "books.json"
    out.write_text(json.dumps(books, indent=2, ensure_ascii=False))
    print(f"Saved {len(books)} books to {out}")
    download_covers(books, data_dir / "covers")
    return out
