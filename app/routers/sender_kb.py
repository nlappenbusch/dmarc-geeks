"""Sender-Knowledge-Base: public-facing /sender + /sender/<slug>.

SEO-Funktion: jeder bekannte E-Mail-Sender bekommt eine indexierbare URL
("Mailchimp DMARC einrichten") — wir konkurrieren dort um Long-Tail-Suchen.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..sender_kb import (CAPABLE_LABELS, CATEGORY_ICONS, CATEGORY_LABELS,
                          all_senders, get_sender, senders_by_category)
from ..templating import render

router = APIRouter()


@router.get("/sender")
def sender_index(request: Request):
    """Liste aller bekannten Sender, gruppiert nach Kategorie."""
    return render(request, "sender_index.html",
                   user=None, tenant=None, active="sender",
                   senders_grouped=senders_by_category(),
                   category_labels=CATEGORY_LABELS,
                   category_icons=CATEGORY_ICONS,
                   capable_labels=CAPABLE_LABELS,
                   total_count=len(all_senders()))


@router.get("/sender/{slug}")
def sender_detail(slug: str, request: Request):
    s = get_sender(slug)
    if s is None:
        raise HTTPException(status_code=404, detail="Sender unbekannt")
    return render(request, "sender_detail.html",
                   user=None, tenant=None, active="sender",
                   sender=s,
                   category_label=CATEGORY_LABELS.get(s.category, s.category),
                   category_icon=CATEGORY_ICONS.get(s.category, "❓"),
                   capable_label=CAPABLE_LABELS.get(s.dmarc_capable, ("?", "muted")))
