"""Wissen/Blog: List + Detail-Routes + sitemap.xml + robots.txt + JSON-LD-Helper.

Liefert die Foundation für SEO-Inbound: indexierbare Long-Form-Inhalte mit
Schema.org Article-Markup, Sitemap der alle Routes inkl. Blog-Artikel listet,
und Robots-Datei.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from ..blog import all_articles, all_tags, get_article
from ..templating import render

router = APIRouter()


@router.get("/blog")
def wissen_index(request: Request, tag: str = ""):
    """Artikel-Liste, optional nach Tag gefiltert."""
    arts = all_articles()
    tag = (tag or "").strip().lower()
    if tag:
        arts = [a for a in arts if tag in [t.lower() for t in a.tags]]
    return render(
        request, "blog_index.html",
        user=None, tenant=None, active="blog",
        articles=arts, active_tag=tag, all_tags=all_tags(),
    )


@router.get("/blog/{slug}")
def wissen_detail(slug: str, request: Request):
    art = get_article(slug)
    if art is None:
        raise HTTPException(status_code=404, detail="Artikel nicht gefunden.")
    # Vor- und Nachfolger fuers Navi
    arts = all_articles()
    idx = next((i for i, a in enumerate(arts) if a.slug == art.slug), None)
    prev_art = arts[idx + 1] if idx is not None and idx + 1 < len(arts) else None
    next_art = arts[idx - 1] if idx is not None and idx > 0 else None
    return render(
        request, "blog_article.html",
        user=None, tenant=None, active="blog",
        article=art, prev_article=prev_art, next_article=next_art,
    )


# ============================================================================
# Sitemap + Robots — kritisch fuer SEO-Inbound, auto-generiert
# ============================================================================

# Statische Marketing-URLs die in der Sitemap erscheinen sollen
_STATIC_URLS = [
    ("/", "weekly", 1.0),
    ("/services", "monthly", 0.9),
    ("/services/dmarc", "monthly", 0.85),
    ("/services/bimi", "monthly", 0.85),
    ("/services/m365", "monthly", 0.8),
    ("/services/seppmail", "monthly", 0.7),
    ("/services/hin", "monthly", 0.7),
    ("/blog", "weekly", 0.85),
    ("/wissen", "monthly", 0.85),
    ("/sender", "monthly", 0.85),
    ("/tool", "monthly", 0.9),
    ("/snapshot", "monthly", 0.9),
    ("/partner-werden", "monthly", 0.8),
    ("/mail-test", "weekly", 0.9),
    ("/services/healthcare-audit", "monthly", 0.85),
    ("/services/therapie-audit", "monthly", 0.85),
    ("/services/psychotherapie-it", "monthly", 0.9),
    ("/services/finma-audit", "monthly", 0.85),
    ("/embed/mailtest/code", "monthly", 0.6),
    ("/demo", "weekly", 0.7),
    ("/vergleich", "monthly", 0.85),
    ("/check", "weekly", 0.85),
    ("/mailtest", "weekly", 0.85),
    ("/dkim-check", "monthly", 0.7),
    ("/bimi-generator", "monthly", 0.7),
    ("/dmarc-generator", "monthly", 0.7),
    ("/spf-generator", "monthly", 0.7),
    ("/report-viewer", "monthly", 0.6),
    ("/kontakt", "monthly", 0.8),
    ("/compliance", "monthly", 0.6),
    ("/impressum", "yearly", 0.3),
    ("/datenschutz", "yearly", 0.3),
]


@router.get("/sitemap.xml")
def sitemap(request: Request):
    """XML-Sitemap aller indexierbaren Pages + Blog-Artikel."""
    base = str(request.base_url).rstrip("/")
    today = datetime.now(timezone.utc).date().isoformat()

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for path, freq, prio in _STATIC_URLS:
        lines.append("  <url>")
        lines.append(f"    <loc>{base}{path}</loc>")
        lines.append(f"    <lastmod>{today}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{prio}</priority>")
        lines.append("  </url>")
    # Blog-Artikel
    for art in all_articles():
        last = (art.date or datetime.now(timezone.utc).date()).isoformat()
        lines.append("  <url>")
        lines.append(f"    <loc>{base}/blog/{art.slug}</loc>")
        lines.append(f"    <lastmod>{last}</lastmod>")
        lines.append("    <changefreq>monthly</changefreq>")
        lines.append("    <priority>0.7</priority>")
        lines.append("  </url>")
    # Sender-Knowledge-Base
    from ..sender_kb import all_senders
    for s in all_senders():
        lines.append("  <url>")
        lines.append(f"    <loc>{base}/sender/{s.slug}</loc>")
        lines.append(f"    <lastmod>{today}</lastmod>")
        lines.append("    <changefreq>monthly</changefreq>")
        lines.append("    <priority>0.65</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml")


@router.get("/robots.txt")
def robots(request: Request):
    base = str(request.base_url).rstrip("/")
    body = (
        "User-agent: *\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /auth/\n"
        "Disallow: /reseller/\n"
        "Disallow: /settings\n"
        "Disallow: /users/\n"
        "Disallow: /mailboxes\n"
        "Disallow: /api-keys\n"
        "Disallow: /webhooks\n"
        "Disallow: /audit-log\n"
        "Disallow: /upload\n"
        "Disallow: /me\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(body)
