from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_user
from ..dns_utils import reverse_lookup
from ..models import AuthResult, Domain, IpAllowlist, Record, Report, User
from ..stats import sender_label
from ..templating import render

router = APIRouter()


def _aligned(dkim, spf) -> bool:
    return dkim == "pass" or spf == "pass"


@router.get("/sources/{ip}")
def ip_detail(
    ip: str,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    # totals across all tenant data
    rows = db.execute(
        select(Record, Report, Domain.name)
        .join(Report, Report.id == Record.report_id)
        .join(Domain, Domain.id == Report.domain_id)
        .where(Record.tenant_id == effective_tenant_id(request, user), Record.source_ip == ip)
        .order_by(desc(Report.date_end))
    ).all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Keine Records für {ip}")

    total = sum(r.count for r, _, _ in rows)
    pass_count = sum(r.count for r, _, _ in rows if _aligned(r.dkim_eval, r.spf_eval))
    fail_count = total - pass_count
    pass_rate = round(100.0 * pass_count / total, 1) if total else 0.0

    # per-domain breakdown
    by_domain: dict[str, dict] = {}
    for rec, _, dname in rows:
        b = by_domain.setdefault(dname, {"name": dname, "total": 0, "pass": 0, "fail": 0})
        b["total"] += rec.count
        if _aligned(rec.dkim_eval, rec.spf_eval):
            b["pass"] += rec.count
        else:
            b["fail"] += rec.count
    for b in by_domain.values():
        b["pass_rate"] = round(100.0 * b["pass"] / b["total"], 1) if b["total"] else 0.0
    domain_rows = sorted(by_domain.values(), key=lambda x: x["total"], reverse=True)

    # daily series
    by_day: dict[str, dict] = {}
    for rec, rep, _ in rows:
        key = rep.date_begin.strftime("%Y-%m-%d") if hasattr(rep.date_begin, "strftime") else str(rep.date_begin)[:10]
        b = by_day.setdefault(key, {"day": key, "pass": 0, "fail": 0})
        if _aligned(rec.dkim_eval, rec.spf_eval):
            b["pass"] += rec.count
        else:
            b["fail"] += rec.count
    series = sorted(by_day.values(), key=lambda x: x["day"])

    # auth-result breakdown
    auth_rows = db.execute(
        select(AuthResult.auth_type, AuthResult.domain, AuthResult.selector,
               AuthResult.result, func.count(AuthResult.id))
        .join(Record, Record.id == AuthResult.record_id)
        .where(Record.tenant_id == effective_tenant_id(request, user), Record.source_ip == ip)
        .group_by(AuthResult.auth_type, AuthResult.domain, AuthResult.selector, AuthResult.result)
        .order_by(desc(func.count(AuthResult.id)))
        .limit(20)
    ).all()

    # allowlist hits across domains
    allow_in = db.execute(
        select(Domain.name, IpAllowlist.label)
        .join(IpAllowlist, IpAllowlist.domain_id == Domain.id)
        .where(IpAllowlist.tenant_id == effective_tenant_id(request, user), IpAllowlist.ip_or_cidr == ip)
    ).all()

    # last 30 records
    recent = [(r, rep, dn) for r, rep, dn in rows[:30]]

    # use first available source_host or look up
    host = next((r.source_host for r, _, _ in rows if r.source_host), None) or reverse_lookup(ip)
    label = sender_label(host, ip)

    return render(
        request,
        "ip_detail.html",
        user=user,
        tenant=effective_tenant(request, user, db),
        ip=ip,
        host=host,
        label=label,
        total=total,
        pass_count=pass_count,
        fail_count=fail_count,
        pass_rate=pass_rate,
        domain_rows=domain_rows,
        series=series,
        auth_rows=auth_rows,
        allow_in=allow_in,
        recent=recent,
        active="reports",
    )
