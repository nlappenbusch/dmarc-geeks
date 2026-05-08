"""Spike-detection on ingest + weekly digest scheduler job."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import session_scope
from .mail import brand_for, render_email, send_mail
from .models import Domain, Record, Report, Reseller, Tenant, TenantSettings, User

log = logging.getLogger(__name__)


def _aligned(dkim, spf) -> bool:
    return dkim == "pass" or spf == "pass"


def _recipients(db: Session, settings: TenantSettings) -> list[str]:
    if settings.digest_recipients:
        return [e.strip() for e in settings.digest_recipients.split(",") if e.strip()]
    return [
        u.email for u in db.execute(
            select(User).where(User.tenant_id == settings.tenant_id, User.is_admin.is_(True))
        ).scalars().all()
    ]


def check_spike(db: Session, *, tenant_id: int, domain: Domain, parsed_count: int) -> None:
    """Compare last 24h vs prior 7d. Send mail if fail-rate jumped."""
    settings = db.get(TenantSettings, tenant_id)
    if not settings or not settings.spike_alert_enabled:
        return
    now = datetime.now(timezone.utc)
    last24 = now - timedelta(hours=24)
    prior_start = now - timedelta(days=8)
    prior_end = last24

    def _rate(start, end) -> tuple[int, float]:
        rows = db.execute(
            select(Record.dkim_eval, Record.spf_eval, func.coalesce(func.sum(Record.count), 0))
            .join(Report, Report.id == Record.report_id)
            .where(Report.domain_id == domain.id,
                   Report.date_begin >= start, Report.date_begin < end)
            .group_by(Record.dkim_eval, Record.spf_eval)
        ).all()
        total = sum(int(c) for *_, c in rows)
        aligned = sum(int(c) for d, s, c in rows if _aligned(d, s))
        if not total:
            return 0, 0.0
        return total, 100.0 * (1 - aligned / total)

    cur_total, cur_fail = _rate(last24, now)
    prev_total, prev_fail = _rate(prior_start, prior_end)
    if cur_total < settings.spike_min_volume or prev_total < settings.spike_min_volume:
        return
    delta = cur_fail - prev_fail
    if delta < settings.spike_threshold_pct:
        return

    recips = _recipients(db, settings)
    if not recips:
        return
    base_url = get_settings().base_url
    link = f"{base_url}/domains/{domain.id}"
    tenant = db.get(Tenant, tenant_id)
    reseller = db.get(Reseller, tenant.reseller_id) if tenant and tenant.reseller_id else None
    brand = brand_for(reseller)
    send_mail(
        to=recips,
        subject=f"{brand['brand_name']}-Alarm: Fail-Rate auf {domain.name} springt um {delta:.1f} %",
        text=(f"Domain: {domain.name}\n"
              f"Letzte 24h: {cur_fail:.1f} % Fail bei {cur_total} Nachrichten\n"
              f"Vorwoche  : {prev_fail:.1f} % Fail bei {prev_total} Nachrichten\n\n"
              f"Top-Quellen prüfen: {link}"),
        html=render_email("spike", domain=domain.name, delta=f"{delta:.1f}",
                            cur_fail=f"{cur_fail:.1f}", cur_total=cur_total,
                            prev_fail=f"{prev_fail:.1f}", prev_total=prev_total,
                            link=link, **brand),
    )


def send_weekly_digest() -> None:
    """Run by scheduler. Sends digest per tenant if enabled and >7 days since last."""
    with session_scope() as db:
        tenants = db.execute(select(Tenant)).scalars().all()
        for tenant in tenants:
            s = db.get(TenantSettings, tenant.id)
            if not s or not s.weekly_digest_enabled:
                continue
            now = datetime.now(timezone.utc)
            last = s.last_digest_sent_at
            if last and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last and (now - last).days < 7:
                continue
            since = now - timedelta(days=7)
            domain_rows = db.execute(
                select(Domain).where(Domain.tenant_id == tenant.id)
            ).scalars().all()
            if not domain_rows:
                continue
            digest_rows: list[dict] = []
            for d in domain_rows:
                rows = db.execute(
                    select(Record.dkim_eval, Record.spf_eval, func.coalesce(func.sum(Record.count), 0))
                    .join(Report, Report.id == Record.report_id)
                    .where(Report.domain_id == d.id, Report.date_begin >= since)
                    .group_by(Record.dkim_eval, Record.spf_eval)
                ).all()
                total = sum(int(c) for *_, c in rows)
                aligned = sum(int(c) for dk, sp, c in rows if _aligned(dk, sp))
                if total == 0:
                    continue
                rate = round(100.0 * aligned / total, 1)
                digest_rows.append({"domain": d.name, "total": total, "pass_rate": rate})
            if not digest_rows:
                continue
            recips = _recipients(db, s)
            if not recips:
                continue
            base_url = get_settings().base_url
            reseller = db.get(Reseller, tenant.reseller_id) if tenant.reseller_id else None
            brand = brand_for(reseller)
            text = (f"Wöchentliche DMARC-Zusammenfassung — Tenant {tenant.name}\n\n"
                    + "\n".join(f"  {r['domain']}: {r['total']} Nachrichten · {r['pass_rate']} % pass"
                                  for r in digest_rows)
                    + f"\n\nDashboard: {base_url}/")
            ok = send_mail(
                to=recips,
                subject=f"{brand['brand_name']} Weekly — {tenant.name}",
                text=text,
                html=render_email("digest", tenant_name=tenant.name, rows=digest_rows,
                                    dashboard_link=f"{base_url}/", **brand),
            )
            if ok:
                s.last_digest_sent_at = now
        # commit happens via session_scope
