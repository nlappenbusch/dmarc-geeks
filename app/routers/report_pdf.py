"""Beautiful printable / PDF-saveable monthly report for a single domain.

Renders a self-contained HTML page with inline SVG charts, brand logo, and
print-CSS so users hit Ctrl+P → "Save as PDF" and get a well-formatted A4 doc.

For real server-side PDF rendering, drop in WeasyPrint later — the template is
already print-stylesheet-aware.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..advisor import evaluate as evaluate_advice
from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_user
from ..models import Domain, Record, Report, Reseller, User
from ..stats import (calendar_heatmap, daily_series, domain_totals,
                       sender_breakdown, top_sources)
from ..templating import render

router = APIRouter()


@router.get("/domains/{domain_id}/report")
def domain_report(
    domain_id: int,
    request: Request,
    days: int = Query(30, ge=7, le=365),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    tid = effective_tenant_id(request, user)
    domain = db.execute(
        select(Domain).where(Domain.id == domain_id, Domain.tenant_id == tid)
    ).scalars().first()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    tenant_obj = effective_tenant(request, user, db)
    reseller = (db.get(Reseller, tenant_obj.reseller_id)
                  if tenant_obj.reseller_id else None)

    totals = domain_totals(db, tenant_id=tid, domain_id=domain.id,
                             since=datetime.now(timezone.utc) - timedelta(days=days))
    series = daily_series(db, tenant_id=tid, domain_id=domain.id, days=days)
    sources = top_sources(db, tenant_id=tid, domain_id=domain.id, days=days, limit=10)
    senders = sender_breakdown(db, tenant_id=tid, domain_id=domain.id, days=days, limit=6)
    advice = evaluate_advice(db, domain)
    heatmap = calendar_heatmap(db, tenant_id=tid, domain_id=domain.id, days=min(days, 84))

    # Build SVG chart for daily series
    chart_svg = _render_daily_svg(series)
    donut_svg = _render_donut_svg(senders)

    # Reseller branding info
    if reseller and not reseller.is_platform:
        brand = {
            "name": reseller.app_name or "DMARC Aggregator",
            "logo": reseller.logo_url,
            "color": reseller.brand_color or "#2563eb",
            "support_email": reseller.support_email,
        }
    else:
        brand = {
            "name": "DMARC Aggregator", "logo": None, "color": "#2563eb",
            "support_email": None,
        }

    period_start = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    period_end = datetime.now(timezone.utc).date()

    return render(
        request,
        "domain_report.html",
        domain=domain,
        tenant=tenant_obj,
        days=days,
        period_start=period_start,
        period_end=period_end,
        totals=totals,
        series=series,
        sources=sources,
        senders=senders,
        advice=advice,
        heatmap=heatmap,
        brand=brand,
        chart_svg=chart_svg,
        donut_svg=donut_svg,
        generated_at=datetime.now(timezone.utc),
        # base.html expects these even though we don't extend it
        user=user,
        active=None,
    )


def _render_daily_svg(series: list[dict]) -> str:
    """Render an SVG bar chart of daily pass/fail."""
    if not series:
        return '<svg viewBox="0 0 800 200"><text x="400" y="100" text-anchor="middle" fill="#9ca3af" font-size="14">Keine Daten im Zeitraum</text></svg>'
    w, h = 800, 220
    pad_l, pad_r, pad_t, pad_b = 50, 20, 30, 40
    cw = w - pad_l - pad_r
    ch = h - pad_t - pad_b
    n = len(series)
    bar_w = max(2, (cw / n) * 0.7)
    gap = (cw / n) * 0.3
    max_total = max((d["pass"] + d["fail"]) for d in series) or 1
    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" font-family="Inter, sans-serif">']
    # axis lines
    for i in range(5):
        y = pad_t + ch * (i / 4)
        v = int(max_total * (1 - i / 4))
        parts.append(f'<line x1="{pad_l}" y1="{y}" x2="{w - pad_r}" y2="{y}" stroke="#e5e7eb" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 4}" text-anchor="end" fill="#9ca3af" font-size="10">{v}</text>')
    # bars
    for i, d in enumerate(series):
        x = pad_l + (cw / n) * i + gap / 2
        total = d["pass"] + d["fail"]
        if total == 0:
            continue
        h_pass = ch * (d["pass"] / max_total)
        h_fail = ch * (d["fail"] / max_total)
        y_fail = pad_t + ch - h_fail
        y_pass = y_fail - h_pass
        if h_pass > 0:
            parts.append(f'<rect x="{x:.1f}" y="{y_pass:.1f}" width="{bar_w:.1f}" height="{h_pass:.1f}" fill="#16a34a" rx="1"/>')
        if h_fail > 0:
            parts.append(f'<rect x="{x:.1f}" y="{y_fail:.1f}" width="{bar_w:.1f}" height="{h_fail:.1f}" fill="#dc2626" rx="1"/>')
    # x-axis labels — first, middle, last
    if n >= 1:
        for idx in (0, n // 2, n - 1):
            d = series[idx]
            label = d["day"][5:]  # MM-DD
            x = pad_l + (cw / n) * idx + bar_w / 2 + gap / 2
            parts.append(f'<text x="{x:.0f}" y="{h - pad_b + 16}" text-anchor="middle" fill="#9ca3af" font-size="10">{label}</text>')
    # legend
    parts.append(f'<rect x="{pad_l}" y="{h - 14}" width="10" height="10" fill="#16a34a" rx="2"/>')
    parts.append(f'<text x="{pad_l + 14}" y="{h - 5}" fill="#374151" font-size="10">Pass</text>')
    parts.append(f'<rect x="{pad_l + 56}" y="{h - 14}" width="10" height="10" fill="#dc2626" rx="2"/>')
    parts.append(f'<text x="{pad_l + 70}" y="{h - 5}" fill="#374151" font-size="10">Fail</text>')
    parts.append("</svg>")
    return "".join(parts)


def _render_donut_svg(senders: list[dict]) -> str:
    """Donut chart of sender breakdown."""
    if not senders:
        return '<svg viewBox="0 0 200 200"><text x="100" y="100" text-anchor="middle" fill="#9ca3af" font-size="12">Keine Daten</text></svg>'
    import math
    total = sum(s["total"] for s in senders) or 1
    cx, cy, r_outer, r_inner = 100, 100, 88, 56
    parts = ['<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" font-family="Inter, sans-serif">']
    angle = -math.pi / 2
    for s in senders:
        frac = s["total"] / total
        a2 = angle + frac * 2 * math.pi
        x1 = cx + r_outer * math.cos(angle); y1 = cy + r_outer * math.sin(angle)
        x2 = cx + r_outer * math.cos(a2);   y2 = cy + r_outer * math.sin(a2)
        x3 = cx + r_inner * math.cos(a2);   y3 = cy + r_inner * math.sin(a2)
        x4 = cx + r_inner * math.cos(angle); y4 = cy + r_inner * math.sin(angle)
        large = 1 if frac > 0.5 else 0
        path = f"M {x1:.2f} {y1:.2f} A {r_outer} {r_outer} 0 {large} 1 {x2:.2f} {y2:.2f} L {x3:.2f} {y3:.2f} A {r_inner} {r_inner} 0 {large} 0 {x4:.2f} {y4:.2f} Z"
        parts.append(f'<path d="{path}" fill="{s["color"]}" stroke="white" stroke-width="2"/>')
        angle = a2
    parts.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" fill="#374151" font-size="22" font-weight="700">{total:,}</text>'.replace(",", " "))
    parts.append(f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" fill="#9ca3af" font-size="10">Nachrichten</text>')
    parts.append("</svg>")
    return "".join(parts)
