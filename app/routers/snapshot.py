"""Domain Health Snapshot — Lead-Magnet flow.

Public form (GET /snapshot) -> Domain + Email Capture -> serverseitiger
DNS-Check + Score -> Lead in DB persistieren -> Email mit Link zum
Print-View an den User -> Operator-Notification.

Idee: aus anonymem Traffic Leads machen. User bekommt einen 1-Pager-PDF-ready
Bericht ("Mail-Sicherheits-Snapshot fuer firma.ch"), wir bekommen Email +
Domain + Health-Score zum Follow-up.

Gleichzeitig wird der Snapshot-Generator auch via CLI (app/cli/snapshot.py)
verwendet fuer Batch-Cold-Outreach -- gleiche Datenquelle, gleicher Code.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dns_utils import full_dns_check, score_check
from ..models import LeadSnapshot
from ..rate_limit import mail_limiter
from ..templating import render

log = logging.getLogger(__name__)

router = APIRouter()


_EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)


def _normalize_domain(raw: str | None) -> str:
    d = (raw or "").strip().lower().rstrip(".")
    if d.startswith("http://"):
        d = d[7:]
    if d.startswith("https://"):
        d = d[8:]
    if "/" in d:
        d = d.split("/", 1)[0]
    # strip Port + uppercase Umlaute bauen, falls jemand "domain.ch:8080" eingibt
    if ":" in d:
        d = d.split(":", 1)[0]
    return d


def _valid_email(e: str) -> bool:
    return bool(_EMAIL_RE.match(e)) and len(e) <= 320


def _valid_domain(d: str) -> bool:
    if not d or "." not in d or len(d) > 253:
        return False
    # Sehr lockere Validierung -- DNS-Lookup spaeter sagt sowieso ob's existiert
    return bool(re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", d))


@router.get("/snapshot")
def snapshot_landing(request: Request):
    """Landing-Seite mit Form fuer Domain-Health-Snapshot."""
    return render(
        request, "snapshot.html",
        user=None, tenant=None, active="snapshot",
        prefill_domain=request.query_params.get("domain", ""),
        sent=False, error=None,
    )


@router.post("/snapshot")
async def snapshot_submit(request: Request, db: Session = Depends(get_db)):
    """Form-Submit: validieren, DNS-Check fahren, Lead persistieren, Mail raus."""
    form = await request.form()
    domain = _normalize_domain(form.get("domain"))
    email = (form.get("email") or "").strip().lower()
    company = (form.get("company") or "").strip()[:255] or None
    first_name = (form.get("first_name") or "").strip()[:120] or None
    consent = bool(form.get("consent"))
    honeypot = (form.get("website") or "").strip()

    # Honeypot: Bots fuellen alles aus, Menschen lassen das (hidden) Feld leer
    if honeypot:
        log.info("snapshot honeypot triggered, ip=%s", request.client.host if request.client else "-")
        return RedirectResponse("/snapshot?sent=1", status_code=303)

    # Validierung
    if not _valid_domain(domain):
        return render(
            request, "snapshot.html",
            user=None, tenant=None, active="snapshot",
            prefill_domain=domain, prefill_email=email,
            prefill_company=company, prefill_first_name=first_name,
            sent=False,
            error="Bitte gültige Domain angeben (z.B. firma.ch — ohne https:// und ohne Pfad).",
        )
    if not _valid_email(email):
        return render(
            request, "snapshot.html",
            user=None, tenant=None, active="snapshot",
            prefill_domain=domain, prefill_email=email,
            prefill_company=company, prefill_first_name=first_name,
            sent=False,
            error="Bitte gültige E-Mail-Adresse angeben.",
        )
    if not consent:
        return render(
            request, "snapshot.html",
            user=None, tenant=None, active="snapshot",
            prefill_domain=domain, prefill_email=email,
            prefill_company=company, prefill_first_name=first_name,
            sent=False,
            error="Bitte bestätige, dass wir dir den Bericht per E-Mail schicken dürfen.",
        )

    # Rate-Limit pro IP -- nicht 50 Snapshots am Stueck
    ip = request.client.host if request.client else "-"
    xff = request.headers.get("x-forwarded-for", "")
    real_ip = xff.split(",")[0].strip() if xff else ip
    if not mail_limiter.take(f"snapshot:{real_ip}"):
        return render(
            request, "snapshot.html",
            user=None, tenant=None, active="snapshot",
            prefill_domain=domain, prefill_email=email,
            prefill_company=company, prefill_first_name=first_name,
            sent=False,
            error="Zu viele Anfragen von dieser IP. Bitte später nochmal probieren.",
        )

    # DNS-Check fahren -- best-effort, bei DNS-Timeout kommt halt ein leeres Resultat
    try:
        check_result = full_dns_check(domain)
        score = score_check(check_result)
    except Exception:  # noqa: BLE001
        log.warning("snapshot DNS check failed for %s", domain, exc_info=True)
        check_result, score = {}, {"total": 0, "grade": "F", "grade_label": "—", "checks": {}, "actions": []}

    grade = score.get("grade", "?")
    total = score.get("total", 0)
    actions = score.get("actions", [])
    top_action = actions[0] if actions else None

    # Lead persistieren (idempotent pro email+domain)
    lead = db.execute(
        select(LeadSnapshot).where(
            LeadSnapshot.email == email,
            LeadSnapshot.domain == domain,
        )
    ).scalars().first()
    if lead is None:
        lead = LeadSnapshot(
            email=email, domain=domain,
            company=company, first_name=first_name,
            grade=grade, score=total,
            top_action=top_action,
            has_dmarc=(check_result.get("dmarc") or {}).get("present", False),
            has_spf=(check_result.get("spf") or {}).get("present", False),
            has_dkim=bool(check_result.get("dkim")),
            source="snapshot-public",
            utm_campaign=request.query_params.get("utm_campaign"),
            requester_ip=real_ip,
        )
        db.add(lead)
    else:
        # Update Snapshot-Werte (User wollte aktualisiert sehen)
        lead.grade = grade
        lead.score = total
        lead.top_action = top_action
        lead.has_dmarc = (check_result.get("dmarc") or {}).get("present", False)
        lead.has_spf = (check_result.get("spf") or {}).get("present", False)
        lead.has_dkim = bool(check_result.get("dkim"))
        if first_name:
            lead.first_name = first_name
        if company:
            lead.company = company
    db.commit()

    # Mails versenden
    s = get_settings()
    base_url = s.base_url.rstrip("/") or "https://dmarc-geeks.ch"
    report_url = f"{base_url}/check?domain={domain}&print=true"

    # Mail 1: an den Lead (mit Link zum Bericht)
    try:
        from .. import mail as mail_mod
        snapshot_html = mail_mod.render_email(
            "snapshot_ready",
            first_name=first_name or "",
            domain=domain,
            grade=grade,
            grade_label=score.get("grade_label", ""),
            score=total,
            actions=actions[:3],
            report_url=report_url,
            base_url=base_url,
            brand_name="DMARC Geeks", brand_color="#2563eb",
            brand_logo=f"{base_url}/static/logo.svg",
        )
        snapshot_text = (
            f"Hallo{(' ' + first_name) if first_name else ''},\n\n"
            f"hier ist dein Mail-Sicherheits-Snapshot fuer {domain}:\n\n"
            f"  Score: {total}/100 (Grade {grade})\n\n"
            f"Top-Empfehlungen:\n"
            + ("\n".join(f"  - {a}" for a in actions[:3]) if actions else "  (keine kritischen Punkte)")
            + f"\n\nKompletter Bericht (PDF-druckbar):\n{report_url}\n\n"
            f"Fragen? Antworte einfach auf diese Mail.\n\n"
            f"Liebe Gruesse\nDMARC Geeks\n"
            f"-- \n{base_url}\n"
        )
        mail_mod.send_mail(
            to=email,
            subject=f"Mail-Sicherheits-Snapshot: {domain} (Grade {grade})",
            text=snapshot_text, html=snapshot_html,
        )

        # Mail 2: Operator-Notification (an uns) -- aehnlich notify_domain_check, aber mit Lead-Daten
        op_subject = f"[Snapshot-Lead] {domain} - Grade {grade} - {email}"
        op_text = (
            f"Neuer Snapshot-Lead!\n\n"
            f"  Email:      {email}\n"
            f"  Domain:     {domain}\n"
            f"  Name:       {first_name or '-'}\n"
            f"  Firma:      {company or '-'}\n"
            f"  Grade:      {grade} ({total}/100)\n"
            f"  Top-Issue:  {top_action or '-'}\n"
            f"  DMARC:      {'ja' if lead.has_dmarc else 'NEIN'}\n"
            f"  SPF:        {'ja' if lead.has_spf else 'NEIN'}\n"
            f"  DKIM:       {'ja' if lead.has_dkim else 'NEIN'}\n"
            f"  IP:         {real_ip}\n"
            f"  UTM:        {request.query_params.get('utm_campaign') or '-'}\n"
            f"  Created:    {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')}\n\n"
            f"-> Bericht:    {report_url}\n"
            f"-> Follow-up: {email}\n"
        )
        op_html = (
            f"<table cellpadding='0' cellspacing='0' style='font:14px -apple-system,Inter,sans-serif;color:#0f172a'>"
            f"<tr><td style='padding:0 0 14px 0'>"
            f"<div style='display:inline-block;background:linear-gradient(135deg,#16a34a,#0d9488);"
            f"color:white;padding:6px 14px;border-radius:999px;font-size:12px;font-weight:600;"
            f"letter-spacing:.04em;text-transform:uppercase'>Snapshot-Lead</div></td></tr>"
            f"<tr><td style='padding:0 0 14px 0'><h2 style='margin:0;font-size:20px'>"
            f"<a href='{report_url}' style='color:#2563eb;text-decoration:none'>{domain}</a> "
            f"&middot; Grade <strong>{grade}</strong> ({total}/100)"
            f"</h2></td></tr>"
            f"<tr><td><table style='border-collapse:collapse;font-size:13.5px'>"
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>E-Mail</td>"
            f"<td><a href='mailto:{email}'>{email}</a></td></tr>"
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>Name</td><td>{first_name or '-'}</td></tr>"
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>Firma</td><td>{company or '-'}</td></tr>"
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>Top-Issue</td><td>{top_action or '-'}</td></tr>"
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>SPF/DKIM/DMARC</td>"
            f"<td>{'✓' if lead.has_spf else '✗'} / {'✓' if lead.has_dkim else '✗'} / {'✓' if lead.has_dmarc else '✗'}</td></tr>"
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>IP</td><td><code>{real_ip}</code></td></tr>"
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>UTM</td><td>{request.query_params.get('utm_campaign') or '-'}</td></tr>"
            f"</table></td></tr>"
            f"<tr><td style='padding:16px 0 0 0'>"
            f"<a href='{report_url}' style='display:inline-block;background:#2563eb;color:white;padding:9px 16px;"
            f"border-radius:8px;text-decoration:none;font-weight:600;margin-right:6px'>Bericht oeffnen</a>"
            f"<a href='mailto:{email}' style='display:inline-block;background:#16a34a;color:white;padding:9px 16px;"
            f"border-radius:8px;text-decoration:none;font-weight:600'>Antworten</a>"
            f"</td></tr></table>"
        )
        from .marketing import _operator_recipients
        mail_mod.send_mail(
            to=_operator_recipients(s),
            subject=op_subject, text=op_text, html=op_html,
            reply_to=email,
        )
    except Exception:  # noqa: BLE001
        log.warning("snapshot mail dispatch failed for %s / %s", email, domain, exc_info=True)

    # Erfolgs-Page
    return render(
        request, "snapshot.html",
        user=None, tenant=None, active="snapshot",
        prefill_domain=domain, prefill_email=email,
        prefill_company=company, prefill_first_name=first_name,
        sent=True, error=None,
        result_grade=grade, result_score=total, result_actions=actions[:3],
        report_url=report_url,
    )
