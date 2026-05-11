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
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import Integer, case, desc, func, select
from sqlalchemy.orm import Session

from ..crawler import crawl_domain
from ..database import get_db
from ..dependencies import require_superadmin
from ..dns_utils import full_dns_check, score_check
from ..models import LeadSnapshot, User
from ..snapshot_render import (
    grade_color,
    normalize_domain,
    render_cold_mail,
    render_snapshot_html,
)
from ..templating import render

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")


# ============================================================================
# Lead-Dashboard
# ============================================================================

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
    # weiss ob sich seit Erstanfrage was geaendert hat
    fresh_score = None
    try:
        result = full_dns_check(lead.domain)
        fresh_score = score_check(result)
    except Exception:  # noqa: BLE001
        log.warning("fresh check failed for %s", lead.domain, exc_info=True)

    return render(
        request, "admin_lead_detail.html",
        user=user, tenant=user.tenant, active="admin",
        lead=lead, fresh_score=fresh_score,
    )


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
    for r in rows_in:
        domain = normalize_domain(r.get("domain") or r.get("Domain") or "")
        if not domain or "." not in domain:
            continue
        email = (r.get("email") or r.get("Email") or "").strip()
        first_name = (r.get("first_name") or r.get("First Name") or r.get("firstname") or "").strip()
        company = (r.get("company") or r.get("Company") or "").strip()

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

        # Optional: als Lead persistieren (mit source="batch-admin" + UTM)
        if persist_leads and email:
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
