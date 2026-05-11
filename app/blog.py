"""Wissen / Blog: liest Markdown-Artikel mit YAML-Frontmatter aus content/wissen/*.md.

Frontmatter-Format pro Datei:

    ---
    title: DMARC bei IONOS einrichten
    slug: dmarc-ionos-einrichten          # optional, sonst aus Dateiname
    description: Schritt-fuer-Schritt-Anleitung fuer den DMARC-Record bei IONOS-DNS.
    date: 2026-05-10
    author: Nils Lappenbusch
    tags: [dmarc, ionos, setup]
    cover: /static/og-image.png            # optional, fallback default-OG
    ---
    Inhalt in Markdown.

Wir cachen die Liste im Prozess (ungeparsed pro File-mtime invalidation) damit
Browser-Requests nicht jedes Mal die Disk hochlesen.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import markdown as _md

log = logging.getLogger(__name__)

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content" / "wissen"


@dataclass
class Article:
    slug: str
    title: str
    description: str
    body_html: str
    date: Optional[date] = None
    author: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    cover: Optional[str] = None
    reading_minutes: int = 3


# ---------- internal frontmatter parser (no dep) ----------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (meta_dict, body_markdown). Very small YAML subset:
    key: value
    key: [a, b, c]
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta_raw = m.group(1)
    body = text[m.end():]
    meta: dict = {}
    for line in meta_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        # List? [a, b, c]
        if v.startswith("[") and v.endswith("]"):
            items = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
            meta[k] = items
        elif v.startswith('"') and v.endswith('"'):
            meta[k] = v[1:-1]
        elif v.startswith("'") and v.endswith("'"):
            meta[k] = v[1:-1]
        else:
            meta[k] = v
    return meta, body


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _reading_minutes(text: str) -> int:
    """Approx 200 WPM."""
    words = len(text.split())
    return max(1, round(words / 200))


# ---------- Loader + Cache ----------

_cache: dict[str, tuple[float, Article]] = {}


def _load_article(path: Path) -> Optional[Article]:
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    cache_key = str(path)
    cached = _cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]

    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)

    slug = meta.get("slug") or path.stem
    title = meta.get("title") or slug.replace("-", " ").title()
    description = meta.get("description", "")
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    cover = meta.get("cover")
    author = meta.get("author")
    dt = _parse_date(meta.get("date"))

    # Markdown -> HTML mit ein paar nuetzlichen Extensions
    html = _md.markdown(
        body,
        extensions=["extra", "sane_lists", "smarty", "toc", "tables", "fenced_code"],
        output_format="html5",
    )

    art = Article(
        slug=slug, title=title, description=description, body_html=html,
        date=dt, author=author, tags=tags, cover=cover,
        reading_minutes=_reading_minutes(body),
    )
    _cache[cache_key] = (mtime, art)
    return art


def all_articles() -> list[Article]:
    """Alle Artikel, neueste zuerst."""
    if not CONTENT_DIR.exists():
        return []
    out: list[Article] = []
    for fp in CONTENT_DIR.glob("*.md"):
        art = _load_article(fp)
        if art is not None:
            out.append(art)
    out.sort(key=lambda a: (a.date or date.min), reverse=True)
    return out


def get_article(slug: str) -> Optional[Article]:
    if not CONTENT_DIR.exists():
        return None
    candidate = CONTENT_DIR / f"{slug}.md"
    if candidate.exists():
        return _load_article(candidate)
    # Fallback: nach slug in Frontmatter suchen
    for art in all_articles():
        if art.slug == slug:
            return art
    return None


def all_tags() -> list[tuple[str, int]]:
    """List of (tag, count), sortiert nach Count desc."""
    counts: dict[str, int] = {}
    for a in all_articles():
        for t in a.tags:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))
