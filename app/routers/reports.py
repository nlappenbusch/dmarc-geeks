import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_user
from ..models import Domain, Record, Report, User
from ..templating import render

router = APIRouter(prefix="/reports")

PAGE_SIZE = 50


def _apply_filters(stmt, *, tenant_id: int, domain_id: Optional[int], q: Optional[str],
                   status_filter: Optional[str], days: int):
    stmt = stmt.where(Report.tenant_id == tenant_id)
    if domain_id:
        stmt = stmt.where(Report.domain_id == domain_id)
    if days and days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = stmt.where(Report.date_begin >= since)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            Report.org_name.ilike(like),
            Report.org_email.ilike(like),
            Report.policy_domain.ilike(like),
            Report.records.any(or_(
                Record.source_ip.ilike(like),
                Record.source_host.ilike(like),
                Record.header_from.ilike(like),
            )),
        ))
    if status_filter == "fail":
        stmt = stmt.where(Report.records.any(
            (Record.dkim_eval != "pass") & (Record.spf_eval != "pass")
        ))
    elif status_filter == "pass":
        stmt = stmt.where(~Report.records.any(
            (Record.dkim_eval != "pass") & (Record.spf_eval != "pass")
        ))
    elif status_filter == "quarantine":
        stmt = stmt.where(Report.records.any(Record.disposition == "quarantine"))
    elif status_filter == "reject":
        stmt = stmt.where(Report.records.any(Record.disposition == "reject"))
    return stmt


@router.get("")
def list_reports(
    request: Request,
    domain_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    days: int = Query(30, ge=0, le=3650),
    page: int = Query(1, ge=1),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    base = (
        select(Report, Domain.name.label("domain_name"),
               func.coalesce(func.sum(Record.count), 0).label("messages"))
        .join(Domain, Domain.id == Report.domain_id)
        .join(Record, Record.report_id == Report.id, isouter=True)
        .group_by(Report.id, Domain.name)
        .order_by(desc(Report.date_end))
    )
    base = _apply_filters(base, tenant_id=effective_tenant_id(request, user), domain_id=domain_id, q=q,
                          status_filter=status_filter, days=days)

    count_stmt = _apply_filters(
        select(func.count(func.distinct(Report.id))),
        tenant_id=effective_tenant_id(request, user), domain_id=domain_id, q=q, status_filter=status_filter, days=days,
    )
    total = db.execute(count_stmt).scalar() or 0

    offset = (page - 1) * PAGE_SIZE
    rows = db.execute(base.offset(offset).limit(PAGE_SIZE)).all()

    domains = db.execute(
        select(Domain).where(Domain.tenant_id == effective_tenant_id(request, user)).order_by(Domain.name)
    ).scalars().all()

    return render(
        request,
        "reports.html",
        user=user,
        tenant=effective_tenant(request, user, db),
        rows=rows,
        domains=domains,
        domain_id=domain_id,
        q=q or "",
        status_filter=status_filter or "",
        days=days,
        page=page,
        page_size=PAGE_SIZE,
        total=total,
        active="reports",
    )


@router.get("/export.csv")
def export_csv(
    request: Request,
    domain_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    days: int = Query(30, ge=0, le=3650),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Report, Domain.name.label("domain_name"))
        .join(Domain, Domain.id == Report.domain_id)
        .order_by(desc(Report.date_end))
    )
    stmt = _apply_filters(stmt, tenant_id=effective_tenant_id(request, user), domain_id=domain_id, q=q,
                          status_filter=status_filter, days=days)
    stmt = stmt.options(selectinload(Report.records))

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "report_id", "domain", "org_name", "org_email", "external_report_id",
            "date_begin", "date_end", "policy_p", "policy_pct",
            "source_ip", "source_host", "count", "disposition",
            "dkim_eval", "spf_eval", "header_from", "envelope_from",
        ])
        yield buf.getvalue(); buf.seek(0); buf.truncate()
        for report, dname in db.execute(stmt).unique().all():
            for rec in report.records:
                w.writerow([
                    report.id, dname, report.org_name, report.org_email, report.external_report_id,
                    report.date_begin.isoformat(), report.date_end.isoformat(),
                    report.policy_p or "", report.policy_pct or "",
                    rec.source_ip, rec.source_host or "", rec.count, rec.disposition or "",
                    rec.dkim_eval or "", rec.spf_eval or "", rec.header_from or "", rec.envelope_from or "",
                ])
                yield buf.getvalue(); buf.seek(0); buf.truncate()

    fn = f"dmarc-export-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(gen(), media_type="text/csv",
                              headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@router.get("/{report_id}")
def report_detail(
    report_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    report = db.execute(
        select(Report)
        .options(selectinload(Report.records).selectinload(Record.auth_results),
                 selectinload(Report.domain))
        .where(Report.id == report_id, Report.tenant_id == effective_tenant_id(request, user))
    ).scalars().first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    total = sum(r.count for r in report.records)
    aligned = sum(r.count for r in report.records if (r.dkim_eval == "pass" or r.spf_eval == "pass"))
    return render(
        request,
        "report_detail.html",
        user=user,
        tenant=effective_tenant(request, user, db),
        report=report,
        total=total,
        aligned=aligned,
        failed=total - aligned,
        active="reports",
    )


@router.get("/{report_id}/raw")
def report_raw(
    report_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    report = db.get(Report, report_id)
    if not report or report.tenant_id != effective_tenant_id(request, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    if not report.raw_xml:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No raw XML stored")
    return Response(report.raw_xml, media_type="application/xml")
