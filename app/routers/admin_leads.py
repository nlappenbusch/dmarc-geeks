"""Admin: Lead-Pipeline + Batch-Snapshot-Tool (Superadmin only).

Drei Bereiche:
- /admin/leads             -> Liste aller Snapshot-Leads, Filter, Status-Update
- /admin/leads/{id}        -> Detail + Notes + Mark-Contacted/Converted
- /admin/batch-snapshot    -> Web-UI fuer Batch-Domain-Snapshot (CSV-Upload)
                              + Cold-Mail-Generator, alles inline ohne Shell.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import Integer, case, desc, func, select
from sqlalchemy.orm import Session

from ..crawler import crawl_domain
from ..database import get_db
from ..dependencies import require_superadmin
from ..discovery import (BRANCH_PRESETS, SWISS_CANTONS, DiscoveryError,
                          check_dmarc_for_prospects, fetch_crtsh_prospects,
                          fetch_osm_prospects, get_preset)
from ..dns_utils import full_dns_check, score_check, has_dmarc_record
from ..models import LeadSnapshot, User
from ..snapshot_render import (
    grade_color,
    normalize_domain,
    render_cold_mail,
    render_cold_mail_html,
    render_followup_mail,
    render_snapshot_html,
)
from ..templating import render

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")


# ============================================================================
# Lead-Dashboard
# ============================================================================

# ============================================================================
# Sales-Playbook (Discovery-Fragen, Einwaende, Call-Skripte)
# ============================================================================

@router.get("/playbook")
def playbook(request: Request, user: User = Depends(require_superadmin)):
    """Sales-Playbook mit Discovery-Fragen, Einwaende-Behandlung, Call-Skripten."""
    return render(request, "admin_playbook.html",
                   user=user, tenant=user.tenant, active="admin")


# Pipeline-Stages mit Reihenfolge, Label, Farbe — fuer Kanban-View
PIPELINE_STAGES = [
    ("open",        "📭 Offen",          "#94a3b8"),
    ("contacted",   "✉ Kontaktiert",     "#3b82f6"),
    ("replied",     "💬 Antwort da",      "#8b5cf6"),
    ("call_booked", "📅 Call gebucht",    "#06b6d4"),
    ("quoted",      "💰 Angebot draussen", "#f59e0b"),
    ("won",         "🎉 Gewonnen",        "#16a34a"),
    ("lost",        "❌ Verloren",        "#dc2626"),
    ("nurture",     "🌱 Nurture (später)", "#a855f7"),
]
STAGE_KEYS = {s[0] for s in PIPELINE_STAGES}


@router.get("/leads/pipeline")
def leads_pipeline(
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Kanban-Pipeline-View aller Leads, gruppiert nach pipeline_status."""
    leads = db.execute(
        select(LeadSnapshot).order_by(desc(LeadSnapshot.created_at))
    ).scalars().all()

    by_stage: dict[str, list] = {s[0]: [] for s in PIPELINE_STAGES}
    for lead in leads:
        st = lead.pipeline_status or "open"
        if st not in by_stage:
            st = "open"
        by_stage[st].append(lead)

    # Reminder-Inbox: alle leads mit reminder_at <= now()
    now = datetime.now(timezone.utc)
    reminders_due = db.execute(
        select(LeadSnapshot).where(
            LeadSnapshot.reminder_at.is_not(None),
            LeadSnapshot.reminder_at <= now,
            LeadSnapshot.pipeline_status.notin_(["won", "lost"]),
        ).order_by(LeadSnapshot.reminder_at)
    ).scalars().all()

    # Stats
    won_value = sum(l.deal_value_chf or 0 for l in leads if l.pipeline_status == "won")
    quoted_value = sum(l.deal_value_chf or 0 for l in leads if l.pipeline_status == "quoted")
    active_count = sum(1 for l in leads
                        if l.pipeline_status not in ("won", "lost"))

    return render(
        request, "admin_leads_pipeline.html",
        user=user, tenant=user.tenant, active="admin",
        stages=PIPELINE_STAGES, by_stage=by_stage,
        reminders_due=reminders_due,
        won_value=won_value, quoted_value=quoted_value,
        active_count=active_count, total_count=len(leads),
    )


@router.post("/leads/{lead_id}/pipeline")
async def lead_pipeline_update(
    lead_id: int,
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Update pipeline_status, reminder_at, deal_value_chf, followup_count."""
    lead = db.get(LeadSnapshot, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    form = await request.form()

    new_status = (form.get("pipeline_status") or "").strip()
    if new_status in STAGE_KEYS:
        old = lead.pipeline_status
        lead.pipeline_status = new_status
        # Bei Status-Wechsel ggfs. timestamps synchronisieren
        if new_status == "contacted" and not lead.contacted_at:
            lead.contacted_at = datetime.now(timezone.utc)
        if new_status == "won" and not lead.converted_at:
            lead.converted_at = datetime.now(timezone.utc)

    # Reminder setzen / löschen
    rem = (form.get("reminder_at") or "").strip()
    if rem == "clear":
        lead.reminder_at = None
    elif rem:
        # Erwartetes Format YYYY-MM-DD oder ISO 8601
        try:
            from dateutil import parser as dtp
            lead.reminder_at = dtp.parse(rem).replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            pass
    elif (form.get("reminder_days") or "").strip():
        # Quick-Set: in X Tagen
        try:
            days = int(form["reminder_days"])
            lead.reminder_at = datetime.now(timezone.utc) + timedelta(days=days)
        except Exception:  # noqa: BLE001
            pass

    # Deal-Wert
    dv = (form.get("deal_value_chf") or "").strip()
    if dv:
        try:
            lead.deal_value_chf = int(dv)
        except ValueError:
            pass

    # Followup-Counter
    if form.get("inc_followup") == "1":
        lead.followup_count = (lead.followup_count or 0) + 1

    # Notes
    notes = form.get("notes")
    if notes is not None:
        lead.notes = notes.strip()[:8000] or None

    db.commit()

    # Redirect dorthin wo wir hergekommen sind
    referer = request.headers.get("referer", "")
    if "/pipeline" in referer:
        return RedirectResponse("/admin/leads/pipeline", status_code=303)
    return RedirectResponse(f"/admin/leads/{lead.id}?saved=1", status_code=303)


@router.get("/leads")
def leads_list(
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
    grade: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
):
    """Liste aller Snapshot-Leads, sortiert nach Erstelldatum (neueste oben)."""
    stmt = select(LeadSnapshot).order_by(desc(LeadSnapshot.created_at))

    if grade and grade in ("A", "B", "C", "D", "F"):
        stmt = stmt.where(LeadSnapshot.grade == grade)
    if status == "open":
        stmt = stmt.where(LeadSnapshot.contacted_at.is_(None))
    elif status == "contacted":
        stmt = stmt.where(
            LeadSnapshot.contacted_at.is_not(None),
            LeadSnapshot.converted_at.is_(None),
        )
    elif status == "converted":
        stmt = stmt.where(LeadSnapshot.converted_at.is_not(None))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            (func.lower(LeadSnapshot.email).like(like))
            | (func.lower(LeadSnapshot.domain).like(like))
            | (func.lower(LeadSnapshot.company).like(like))
        )

    leads = db.execute(stmt.limit(500)).scalars().all()

    # Aggregat-Kennzahlen (open = noch nicht kontaktiert)
    totals = db.execute(
        select(
            func.count(LeadSnapshot.id).label("total"),
            func.coalesce(func.sum(
                case((LeadSnapshot.contacted_at.is_(None), 1), else_=0)
            ), 0).label("open"),
            func.count(LeadSnapshot.converted_at).label("converted"),
        )
    ).one()

    # Grade-Verteilung
    grade_dist = db.execute(
        select(LeadSnapshot.grade, func.count(LeadSnapshot.id))
        .group_by(LeadSnapshot.grade)
    ).all()
    grade_counts = {g or "?": c for g, c in grade_dist}

    return render(
        request, "admin_leads.html",
        user=user, tenant=user.tenant, active="admin",
        leads=leads,
        filter_grade=grade, filter_status=status, filter_q=q,
        total_count=totals.total or 0,
        open_count=totals.open or 0,
        converted_count=totals.converted or 0,
        grade_counts=grade_counts,
    )


@router.get("/leads/{lead_id}")
def lead_detail(
    lead_id: int,
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    lead = db.get(LeadSnapshot, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Auf-die-Schnelle einen frischen Check fahren, damit Operator vor dem Call
    # weiss ob sich seit Erstanfrage was geaendert hat. Wenn das klappt, gleich
    # die personalisierte Cold-Mail-HTML mit den frischen Daten generieren --
    # so sieht der Operator direkt was er senden koennte.
    fresh_score = None
    fresh_result = None
    cold_mail = None
    try:
        fresh_result = full_dns_check(lead.domain)
        fresh_score = score_check(fresh_result)
    except Exception:  # noqa: BLE001
        log.warning("fresh check failed for %s", lead.domain, exc_info=True)

    if fresh_score and fresh_result:
        try:
            cold_mail = render_cold_mail_html(
                lead.domain, fresh_score,
                first_name=lead.first_name or "",
                company=lead.company or "",
                email=lead.email,
                check_result=fresh_result,
            )
        except Exception:  # noqa: BLE001
            log.warning("cold-mail render failed for %s", lead.domain, exc_info=True)

    return render(
        request, "admin_lead_detail.html",
        user=user, tenant=user.tenant, active="admin",
        lead=lead, fresh_score=fresh_score, cold_mail=cold_mail,
    )


@router.post("/leads/{lead_id}/rerun")
async def lead_rerun(
    lead_id: int,
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Re-run: frischer Crawl (Email/Phone update) + DNS-Check + Score-Update.
    Updated den Lead in der DB und leitet auf die Detail-Page zurueck (mit
    aktualisierten Werten + neuer Cold-Mail)."""
    lead = db.get(LeadSnapshot, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Crawler (Email + Firma evtl. aktualisieren — falls Website seit Lead-Anlage
    # geändert hat)
    try:
        cr = crawl_domain(lead.domain, rate_limit_seconds=0.5, max_pages=4)
        if cr.company_name and not lead.company:
            lead.company = cr.company_name
    except Exception:  # noqa: BLE001
        log.warning("rerun crawl failed for %s", lead.domain, exc_info=True)

    # DNS-Check fresh + Score
    try:
        fresh_result = full_dns_check(lead.domain)
        sc = score_check(fresh_result)
        lead.grade = sc.get("grade")
        lead.score = sc.get("total")
        actions = sc.get("actions") or []
        lead.top_action = actions[0] if actions else None
        lead.has_dmarc = (fresh_result.get("dmarc") or {}).get("present", False)
        lead.has_spf = (fresh_result.get("spf") or {}).get("present", False)
        lead.has_dkim = bool(fresh_result.get("dkim"))
    except Exception:  # noqa: BLE001
        log.warning("rerun dns failed for %s", lead.domain, exc_info=True)

    db.commit()
    return RedirectResponse(f"/admin/leads/{lead.id}?rerun=1", status_code=303)


@router.post("/leads/{lead_id}")
async def lead_update(
    lead_id: int,
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Notes + Status-Updates speichern."""
    form = await request.form()
    lead = db.get(LeadSnapshot, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    action = (form.get("action") or "").strip()
    notes = form.get("notes")
    if notes is not None:
        lead.notes = notes.strip()[:8000] or None

    if action == "mark_contacted":
        lead.contacted_at = datetime.now(timezone.utc)
    elif action == "mark_uncontacted":
        lead.contacted_at = None
        lead.converted_at = None
    elif action == "mark_converted":
        if lead.contacted_at is None:
            lead.contacted_at = datetime.now(timezone.utc)
        lead.converted_at = datetime.now(timezone.utc)
    elif action == "mark_unconverted":
        lead.converted_at = None
    elif action == "delete":
        db.delete(lead)
        db.commit()
        return RedirectResponse("/admin/leads?deleted=1", status_code=303)

    db.commit()
    return RedirectResponse(f"/admin/leads/{lead.id}?saved=1", status_code=303)


# ============================================================================
# Batch-Snapshot-Tool (Web-UI)
# ============================================================================

@router.get("/batch-snapshot")
def batch_snapshot_form(
    request: Request,
    user: User = Depends(require_superadmin),
):
    """Form zum Hochladen einer CSV mit Domain-Liste."""
    return render(
        request, "admin_batch_snapshot.html",
        user=user, tenant=user.tenant, active="admin",
        results=None, error=None,
    )


@router.post("/batch-snapshot")
async def batch_snapshot_run(
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """CSV verarbeiten: pro Domain DNS-Check + optional Lead-Persist + Output."""
    form = await request.form()
    csv_file: Optional[UploadFile] = form.get("csv_file")
    paste_text = (form.get("paste_text") or "").strip()
    min_grade = (form.get("min_grade") or "").strip() or None
    persist_leads = bool(form.get("persist_leads"))
    limit_raw = (form.get("limit") or "").strip()
    try:
        limit = int(limit_raw) if limit_raw else 50
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 500))

    # Quelle: entweder Upload oder Paste
    raw_csv = ""
    if csv_file is not None and hasattr(csv_file, "read"):
        data = await csv_file.read()
        if data:
            raw_csv = data.decode("utf-8", errors="replace")
    if not raw_csv and paste_text:
        # Paste-Mode: koennte einfach eine Domain pro Zeile sein, oder CSV.
        # Fallback: wenn keine Komma drin -> als "nur Domains" interpretieren.
        if "," not in paste_text.splitlines()[0]:
            raw_csv = "domain\n" + paste_text
        else:
            raw_csv = paste_text

    if not raw_csv:
        return render(
            request, "admin_batch_snapshot.html",
            user=user, tenant=user.tenant, active="admin",
            results=None, error="Bitte CSV hochladen oder Domains in das Textfeld einfuegen.",
        )

    # CSV parsen
    try:
        reader = csv.DictReader(io.StringIO(raw_csv))
        rows_in = list(reader)
    except Exception as e:  # noqa: BLE001
        return render(
            request, "admin_batch_snapshot.html",
            user=user, tenant=user.tenant, active="admin",
            results=None, error=f"CSV konnte nicht gelesen werden: {e}",
        )

    if not rows_in:
        return render(
            request, "admin_batch_snapshot.html",
            user=user, tenant=user.tenant, active="admin",
            results=None, error="Keine Datenzeilen gefunden (oder Header fehlt).",
        )

    rows_in = rows_in[:limit]
    grade_order = ["A", "B", "C", "D", "F"]
    min_idx = grade_order.index(min_grade) if min_grade in grade_order else None

    results: list[dict] = []
    persist_skipped_no_email = 0
    persist_saved = 0
    for r in rows_in:
        domain = normalize_domain(r.get("domain") or r.get("Domain") or "")
        if not domain or "." not in domain:
            continue
        email = (r.get("email") or r.get("Email") or "").strip()
        first_name = (r.get("first_name") or r.get("First Name") or r.get("firstname") or "").strip()
        company = (r.get("company") or r.get("Company") or "").strip()
        if persist_leads and not email:
            persist_skipped_no_email += 1

        try:
            check_result = full_dns_check(domain)
            score = score_check(check_result)
        except Exception as e:  # noqa: BLE001
            log.warning("batch-snapshot check failed for %s: %s", domain, e)
            continue

        grade = score.get("grade", "?")
        skip_outputs = False
        if min_idx is not None:
            try:
                if grade_order.index(grade) < min_idx:
                    skip_outputs = True
            except ValueError:
                pass

        cold_mail = (None if skip_outputs
                      else render_cold_mail(domain, score, first_name=first_name,
                                             company=company, email=email))

        # Optional: als Lead persistieren (mit source="batch-admin" + UTM).
        # WICHTIG: ohne Email koennen wir nichts speichern (DB-Constraint).
        # Pro Zeile ohne Email zaehlen wir hoch -> Warning oben in der UI.
        if persist_leads and email:
            persist_saved += 1
            try:
                lead = db.execute(
                    select(LeadSnapshot).where(
                        LeadSnapshot.email == email.lower(),
                        LeadSnapshot.domain == domain,
                    )
                ).scalars().first()
                if lead is None:
                    lead = LeadSnapshot(
                        email=email.lower(), domain=domain,
                        company=company or None, first_name=first_name or None,
                        grade=grade, score=score.get("total"),
                        top_action=(score.get("actions") or [None])[0],
                        has_dmarc=(check_result.get("dmarc") or {}).get("present", False),
                        has_spf=(check_result.get("spf") or {}).get("present", False),
                        has_dkim=bool(check_result.get("dkim")),
                        source="batch-admin",
                    )
                    db.add(lead)
                else:
                    lead.grade = grade
                    lead.score = score.get("total")
            except Exception:  # noqa: BLE001
                log.warning("persist lead failed for %s/%s", email, domain, exc_info=True)

        results.append({
            "domain": domain,
            "email": email,
            "first_name": first_name,
            "company": company,
            "grade": grade,
            "grade_color": grade_color(grade),
            "score": score.get("total", 0),
            "actions": score.get("actions") or [],
            "top_action": (score.get("actions") or [""])[0],
            "has_dmarc": (check_result.get("dmarc") or {}).get("present", False),
            "has_spf": (check_result.get("spf") or {}).get("present", False),
            "has_dkim": bool(check_result.get("dkim")),
            "cold_mail": cold_mail,
            "skip_outputs": skip_outputs,
        })

    if persist_leads:
        db.commit()

    return render(
        request, "admin_batch_snapshot.html",
        user=user, tenant=user.tenant, active="admin",
        results=results, error=None,
        meta={
            "total": len(results),
            "with_outputs": sum(1 for r in results if not r["skip_outputs"]),
            "by_grade": {g: sum(1 for r in results if r["grade"] == g) for g in grade_order},
            "min_grade": min_grade,
            "persist_leads": persist_leads,
            "persist_saved": persist_saved,
            "persist_skipped_no_email": persist_skipped_no_email,
        },
    )


@router.get("/batch-snapshot/snapshot/{domain}")
def batch_snapshot_one(
    domain: str,
    user: User = Depends(require_superadmin),
):
    """Liefert das Standalone-HTML-Snapshot fuer eine einzelne Domain — zum
    Speichern, Drucken oder Versenden. Wird vom Batch-Tool als Link benutzt."""
    domain = normalize_domain(domain)
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    try:
        result = full_dns_check(domain)
        score = score_check(result)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"DNS check failed: {e}")
    html = render_snapshot_html(domain, result, score)
    return HTMLResponse(html)


@router.get("/leads/{lead_id}/followup/{seq}")
def lead_followup(
    lead_id: int,
    seq: int,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Followup-Mail-Template Nr 1/2/3 als text/plain — copy&paste in Outlook."""
    lead = db.get(LeadSnapshot, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if seq not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="seq must be 1, 2 or 3")
    out = render_followup_mail(
        lead.domain, seq,
        first_name=lead.first_name or "",
        grade=lead.grade or "F",
    )
    text = f"Betreff: {out['subject']}\n\n{out['plain']}"
    return Response(text, media_type="text/plain; charset=utf-8")


@router.get("/batch-snapshot/coldmail/{domain}")
def batch_snapshot_coldmail(
    domain: str,
    user: User = Depends(require_superadmin),
    first_name: str = "",
    company: str = "",
    email: str = "",
):
    """Liefert das Cold-Mail-Template als reinen Text — zum Copy&Paste in Outlook."""
    domain = normalize_domain(domain)
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    try:
        result = full_dns_check(domain)
        score = score_check(result)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"DNS check failed: {e}")
    text = render_cold_mail(domain, score, first_name=first_name,
                             company=company, email=email)
    return Response(text, media_type="text/plain; charset=utf-8")


# ============================================================================
# Contact-Crawler (KMU-Email-Adressen ernten)
# ============================================================================

@router.get("/crawl-contacts")
def crawl_contacts_form(
    request: Request,
    user: User = Depends(require_superadmin),
):
    """Form-Page fuer den Kontakt-Crawler."""
    return render(
        request, "admin_crawl_contacts.html",
        user=user, tenant=user.tenant, active="admin",
        results=None, error=None,
    )


@router.post("/crawl-contacts")
async def crawl_contacts_run(
    request: Request,
    user: User = Depends(require_superadmin),
):
    """Liste von Domains crawlen, fuer jede Domain Emails+Phones+Firma extrahieren."""
    form = await request.form()
    paste_text = (form.get("domains") or "").strip()
    limit_raw = (form.get("limit") or "").strip()
    try:
        limit = int(limit_raw) if limit_raw else 25
    except ValueError:
        limit = 25
    limit = max(1, min(limit, 100))  # max 100 pro Run (Performance)

    if not paste_text:
        return render(
            request, "admin_crawl_contacts.html",
            user=user, tenant=user.tenant, active="admin",
            results=None, error="Bitte mindestens eine Domain eintragen.",
        )

    # Eine Domain pro Zeile (oder CSV — wir nehmen die erste Spalte)
    domains = []
    for line in paste_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # CSV-Fallback: erste Spalte
        if "," in line:
            line = line.split(",", 1)[0].strip()
        domains.append(line)
    domains = domains[:limit]

    if not domains:
        return render(
            request, "admin_crawl_contacts.html",
            user=user, tenant=user.tenant, active="admin",
            results=None, error="Keine validen Domains in deiner Eingabe gefunden.",
        )

    results = []
    for d in domains:
        try:
            r = crawl_domain(d, rate_limit_seconds=0.7, max_pages=4)
        except Exception as e:  # noqa: BLE001
            log.warning("crawl error for %s", d, exc_info=True)
            r = type("R", (), {})()
            r.domain = d
            r.company_name = None
            r.emails = []
            r.phones = []
            r.primary_email = None
            r.primary_phone = None
            r.pages_crawled = []
            r.error = str(e)
        results.append(r)

    # Stats
    with_email = sum(1 for r in results if r.primary_email)
    with_phone = sum(1 for r in results if r.primary_phone)
    unreachable = sum(1 for r in results if r.error)

    return render(
        request, "admin_crawl_contacts.html",
        user=user, tenant=user.tenant, active="admin",
        results=results, error=None,
        meta={
            "total": len(results),
            "with_email": with_email,
            "with_phone": with_phone,
            "unreachable": unreachable,
        },
    )


@router.post("/crawl-contacts/export-csv")
async def crawl_contacts_export(
    request: Request,
    user: User = Depends(require_superadmin),
):
    """Crawl-Resultate als CSV runterladen — direkt verwendbar als Input fuer
    /admin/batch-snapshot (Spalten: domain,email,first_name,company)."""
    form = await request.form()
    paste_text = (form.get("domains") or "").strip()
    limit = 100
    domains = []
    for line in paste_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            line = line.split(",", 1)[0].strip()
        domains.append(line)
    domains = domains[:limit]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["domain", "email", "first_name", "company", "phone", "all_emails"])
    for d in domains:
        try:
            r = crawl_domain(d, rate_limit_seconds=0.7, max_pages=4)
            writer.writerow([
                r.domain,
                r.primary_email or "",
                "",  # first_name: muss man nachher noch erraten/researchen
                r.company_name or "",
                r.primary_phone or "",
                ";".join(r.emails),
            ])
        except Exception as e:  # noqa: BLE001
            log.warning("export crawl error for %s: %s", d, e)
            writer.writerow([d, "", "", "", "", ""])

    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="crawl-contacts.csv"'},
    )


# ----------------------------------------------------------------------------
# Streaming-Endpoint: crawl + DNS-Check + Cold-Mail PRO DOMAIN, live per
# NDJSON streamen damit User sofort Feedback hat statt einer ewig hängenden
# Form-Submission. Frontend liest mit ReadableStream und rendert pro Zeile.
# ----------------------------------------------------------------------------

def _parse_domain_input(paste_text: str, limit: int = 100) -> list[str]:
    """Aus dem Paste-Field eine saubere Domain-Liste extrahieren."""
    domains: list[str] = []
    seen: set[str] = set()
    for line in paste_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            line = line.split(",", 1)[0].strip()
        d = normalize_domain(line)
        if d and "." in d and d not in seen:
            seen.add(d)
            domains.append(d)
        if len(domains) >= limit:
            break
    return domains


@router.post("/crawl-contacts/stream")
async def crawl_contacts_stream(
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """NDJSON-Stream: pro Domain ein JSON-Event mit (crawl + DNS + cold-mail).

    Events:
      {type:"start", total:N}
      {type:"progress", i, domain, phase:"crawl"|"dns"|"mail"}
      {type:"result", i, total, domain, company_name, primary_email, ...,
                      grade, score, cold_mail}
      {type:"done", total, with_email, with_phone, unreachable}
    """
    form = await request.form()
    paste_text = (form.get("domains") or "").strip()
    try:
        limit = int((form.get("limit") or "25").strip())
    except ValueError:
        limit = 25
    limit = max(1, min(limit, 100))
    do_dns = bool(form.get("do_dns"))
    do_mail = bool(form.get("do_mail"))
    persist_leads = bool(form.get("persist_leads"))

    domains = _parse_domain_input(paste_text, limit=limit)

    def sse(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False) + "\n"

    def generate():
        # Initial event
        yield sse({"type": "start", "total": len(domains)})

        if not domains:
            yield sse({"type": "done", "total": 0, "with_email": 0,
                        "with_phone": 0, "unreachable": 0,
                        "error": "Keine validen Domains gefunden."})
            return

        with_email = with_phone = unreachable = 0

        for i, d in enumerate(domains):
            # Progress: crawl
            yield sse({"type": "progress", "i": i, "total": len(domains),
                        "domain": d, "phase": "crawl"})

            try:
                cr = crawl_domain(d, rate_limit_seconds=0.6, max_pages=4)
            except Exception as e:  # noqa: BLE001
                log.warning("stream crawl failed for %s", d, exc_info=True)
                cr = type("R", (), {})()
                cr.domain = d
                cr.company_name = None
                cr.emails = []
                cr.phones = []
                cr.primary_email = None
                cr.primary_phone = None
                cr.pages_crawled = []
                cr.error = f"crawl error: {e}"

            grade = None
            score_total = 0
            actions: list[str] = []
            cold_mail = None
            dns_error = None
            dns_result: dict = {}

            if do_dns and not cr.error:
                yield sse({"type": "progress", "i": i, "total": len(domains),
                            "domain": d, "phase": "dns"})
                try:
                    dns_result = full_dns_check(d)
                    score = score_check(dns_result)
                    grade = score.get("grade")
                    score_total = score.get("total", 0)
                    actions = score.get("actions", [])
                except Exception as e:  # noqa: BLE001
                    log.warning("stream dns failed for %s: %s", d, e)
                    dns_error = str(e)

                if do_mail and grade:
                    yield sse({"type": "progress", "i": i, "total": len(domains),
                                "domain": d, "phase": "mail"})
                    try:
                        cold_mail = render_cold_mail_html(
                            d, score,
                            first_name="",
                            company=cr.company_name or "",
                            email=cr.primary_email or "",
                            check_result=dns_result,
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning("stream mail failed for %s: %s", d, e)

            if cr.primary_email:
                with_email += 1
            if cr.primary_phone:
                with_phone += 1
            if cr.error:
                unreachable += 1

            # Optional: als Lead persistieren -- nur wenn wir eine Email haben.
            # Source = "crawler-batch" damit man Crawler-Leads von Snapshot-
            # Public-Form-Leads unterscheiden kann.
            persisted = False
            if persist_leads and cr.primary_email and not cr.error:
                try:
                    email_lower = cr.primary_email.lower()
                    lead = db.execute(
                        select(LeadSnapshot).where(
                            LeadSnapshot.email == email_lower,
                            LeadSnapshot.domain == d,
                        )
                    ).scalars().first()
                    if lead is None:
                        lead = LeadSnapshot(
                            email=email_lower, domain=d,
                            company=cr.company_name or None,
                            first_name=None,  # haben wir aus Crawl nicht
                            grade=grade, score=score_total,
                            top_action=(actions[0] if actions else None),
                            has_dmarc=None, has_spf=None, has_dkim=None,
                            source="crawler-batch",
                        )
                        if do_dns:
                            try:
                                # Erkennt aus dem dns_result die present-Flags
                                lead.has_dmarc = (dns_result.get("dmarc") or {}).get("present", False)
                                lead.has_spf   = (dns_result.get("spf") or {}).get("present", False)
                                lead.has_dkim  = bool(dns_result.get("dkim"))
                            except Exception:  # noqa: BLE001
                                pass
                        db.add(lead)
                    else:
                        if grade:
                            lead.grade = grade
                            lead.score = score_total
                        if cr.company_name and not lead.company:
                            lead.company = cr.company_name
                    db.commit()
                    persisted = True
                except Exception:  # noqa: BLE001
                    log.warning("crawler persist failed for %s/%s",
                                cr.primary_email, d, exc_info=True)
                    db.rollback()

            yield sse({
                "type": "result",
                "persisted": persisted,
                "i": i,
                "total": len(domains),
                "domain": cr.domain,
                "company_name": cr.company_name,
                "primary_email": cr.primary_email,
                "all_emails": cr.emails[:5],
                "primary_phone": cr.primary_phone,
                "phones": cr.phones,
                "pages_crawled": len(cr.pages_crawled),
                "error": cr.error,
                "grade": grade,
                "grade_color": grade_color(grade) if grade else None,
                "score": score_total,
                "top_action": (actions[0] if actions else None),
                "dns_error": dns_error,
                # cold_mail ist jetzt ein dict {subject, html, plain} oder None
                "cold_mail_subject": cold_mail["subject"] if cold_mail else None,
                "cold_mail_html":    cold_mail["html"] if cold_mail else None,
                "cold_mail_plain":   cold_mail["plain"] if cold_mail else None,
            })

        yield sse({
            "type": "done",
            "total": len(domains),
            "with_email": with_email,
            "with_phone": with_phone,
            "unreachable": unreachable,
        })

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            # Wichtig: kein Buffer-Caching durch den Reverse-Proxy (NPM/nginx)
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ============================================================================
# Prospect-Discovery via crt.sh (Certificate-Transparency-Logs)
# ============================================================================

@router.get("/discover")
def discover_form(
    request: Request,
    user: User = Depends(require_superadmin),
):
    """Form-Page fuer den Prospect-Finder."""
    return render(
        request, "admin_discover.html",
        user=user, tenant=user.tenant, active="discover",
        presets=BRANCH_PRESETS, cantons=SWISS_CANTONS,
    )


@router.post("/discover/stream")
async def discover_stream(
    request: Request,
    user: User = Depends(require_superadmin),
):
    """NDJSON-Stream: OSM- oder crt.sh-Query + optionaler DMARC-Check.

    source: "osm" (default) oder "crtsh"
    - osm  -> braucht preset_key + optional canton
    - crtsh -> braucht keyword + tld

    Events:
      {type:"fetch", msg}
      {type:"start", total, source}
      {type:"progress", i, total, domain, phase:"dmarc"}
      {type:"result", domain, company_name, phone, city, has_dmarc, ...}
      {type:"done", total, without_dmarc, with_dmarc, skipped, error?}
    """
    form = await request.form()
    source = (form.get("source") or "osm").strip().lower()
    preset_key = (form.get("preset_key") or "").strip()
    canton = (form.get("canton") or "").strip()
    keyword = (form.get("keyword") or "").strip().lower()
    tld = (form.get("tld") or "ch").strip().lower().lstrip(".")
    try:
        limit = int((form.get("limit") or "50").strip())
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))
    check_dmarc = bool(form.get("check_dmarc"))
    only_no_dmarc = bool(form.get("only_no_dmarc"))

    def sse(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False) + "\n"

    def generate():
        # ---- Source: OSM (primär, strukturiert) ----
        if source == "osm":
            preset = get_preset(preset_key)
            if not preset:
                yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                            "with_dmarc": 0, "skipped": 0,
                            "error": "Bitte eine Branche oben auswählen."})
                return

            canton_label = canton or "ganze Schweiz"
            yield sse({"type": "fetch",
                        "msg": f"OpenStreetMap (Overpass): {preset['label']} in {canton_label} — typisch 3-10 Sekunden …"})

            try:
                prospects = fetch_osm_prospects(
                    preset["osm_filter"], canton=canton, limit=limit
                )
            except DiscoveryError as e:
                yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                            "with_dmarc": 0, "skipped": 0,
                            "error": f"OSM-Fehler: {e}"})
                return
            except Exception as e:  # noqa: BLE001
                log.warning("osm fetch failed", exc_info=True)
                yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                            "with_dmarc": 0, "skipped": 0,
                            "error": f"OSM-Fehler: {e}"})
                return

        # ---- Source: crt.sh (Fallback für Custom-Keyword) ----
        elif source == "crtsh":
            if not keyword:
                yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                            "with_dmarc": 0, "skipped": 0,
                            "error": "Custom-Keyword fehlt."})
                return
            yield sse({"type": "fetch",
                        "msg": f"crt.sh: %{keyword}%.{tld} — kann ein paar Sekunden dauern …"})
            try:
                prospects = fetch_crtsh_prospects(keyword, tld, limit=limit)
            except DiscoveryError as e:
                yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                            "with_dmarc": 0, "skipped": 0,
                            "error": str(e)})
                return
            except Exception as e:  # noqa: BLE001
                log.warning("crt.sh fetch failed", exc_info=True)
                yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                            "with_dmarc": 0, "skipped": 0,
                            "error": f"crt.sh-Fehler: {e}"})
                return
        else:
            yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                        "with_dmarc": 0, "skipped": 0,
                        "error": f"Unbekannte Source: {source}"})
            return

        if not prospects:
            yield sse({"type": "done", "total": 0, "without_dmarc": 0,
                        "with_dmarc": 0, "skipped": 0,
                        "error": "Keine Domains gefunden — andere Branche/Kanton/Keyword probieren?"})
            return

        yield sse({"type": "start", "total": len(prospects), "source": source})

        without_dmarc = with_dmarc = skipped = 0

        for i, p in enumerate(prospects):
            if check_dmarc:
                yield sse({"type": "progress", "i": i, "total": len(prospects),
                            "domain": p.domain, "phase": "dmarc"})
                try:
                    p.has_dmarc = has_dmarc_record(p.domain)
                except Exception:  # noqa: BLE001
                    p.has_dmarc = None

            if check_dmarc and only_no_dmarc and p.has_dmarc is True:
                skipped += 1
                continue

            if p.has_dmarc is True:
                with_dmarc += 1
            elif p.has_dmarc is False:
                without_dmarc += 1

            yield sse({
                "type": "result",
                "i": i,
                "total": len(prospects),
                "domain": p.domain,
                "company_name": p.company_name,
                "phone": p.phone,
                "city": p.city,
                "website": p.website,
                "cert_count": p.cert_count,
                "sans": p.seen_sans,
                "has_dmarc": p.has_dmarc,
            })

        yield sse({
            "type": "done",
            "total": len(prospects),
            "without_dmarc": without_dmarc,
            "with_dmarc": with_dmarc,
            "skipped": skipped,
        })

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
