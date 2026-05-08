from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_user
from ..models import Domain, User
from ..onboarding import compute as compute_checklist
from ..stats import (calendar_heatmap, daily_series, domain_summaries, domain_totals,
                       sankey_data, sender_breakdown, sender_daily_stack, top_sources)
from ..templating import render

router = APIRouter()


@router.get("/dashboard")
def home(
    request: Request,
    domain_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=3650),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    tid = effective_tenant_id(request, user)
    tenant_obj = effective_tenant(request, user, db)
    selected_domain = None
    if domain_id:
        selected_domain = db.execute(
            select(Domain).where(Domain.id == domain_id, Domain.tenant_id == tid)
        ).scalars().first()
        if not selected_domain:
            raise HTTPException(status_code=404, detail="Domain not found")

    summaries = domain_summaries(db, tenant_id=tid, days=days)
    if selected_domain:
        summaries = [s for s in summaries if s["domain"].id == selected_domain.id]

    totals = domain_totals(db, tenant_id=tid,
                            domain_id=domain_id if selected_domain else None)
    series = daily_series(db, tenant_id=tid,
                            domain_id=domain_id if selected_domain else None, days=days)
    sources = top_sources(db, tenant_id=tid,
                            domain_id=domain_id if selected_domain else None,
                            days=days, limit=10)
    senders = sender_breakdown(db, tenant_id=tid,
                                 domain_id=domain_id if selected_domain else None, days=days)
    sender_stack = sender_daily_stack(db, tenant_id=tid,
                                        domain_id=domain_id if selected_domain else None,
                                        days=days)
    sankey = sankey_data(db, tenant_id=tid,
                          domain_id=domain_id if selected_domain else None, days=days)
    heatmap = calendar_heatmap(db, tenant_id=tid,
                                  domain_id=domain_id if selected_domain else None, days=84)
    checklist = compute_checklist(db, tenant_obj)

    all_domains = db.execute(
        select(Domain).where(Domain.tenant_id == tid).order_by(Domain.name)
    ).scalars().all()

    return render(
        request,
        "dashboard.html",
        user=user,
        tenant=tenant_obj,
        summaries=summaries,
        totals=totals,
        series=series,
        sources=sources,
        senders=senders,
        sender_stack=sender_stack,
        sankey=sankey,
        heatmap=heatmap,
        checklist=checklist,
        all_domains=all_domains,
        selected_domain=selected_domain,
        domain_id=domain_id,
        days=days,
        active="dashboard",
    )
