"""Aggregations used by dashboard and domain detail views."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .models import Domain, Record, Report, Tenant


@dataclass
class DispositionTotals:
    pass_count: int = 0
    fail_count: int = 0
    quarantine_count: int = 0
    reject_count: int = 0
    total: int = 0

    @property
    def pass_rate(self) -> float:
        return 0.0 if self.total == 0 else round(100.0 * self.pass_count / self.total, 1)


def _aligned(record_dkim: Optional[str], record_spf: Optional[str]) -> bool:
    return (record_dkim == "pass") or (record_spf == "pass")


def domain_totals(db: Session, *, tenant_id: int, domain_id: Optional[int] = None,
                  since: Optional[datetime] = None) -> DispositionTotals:
    q = (
        select(
            Record.dkim_eval,
            Record.spf_eval,
            Record.disposition,
            func.coalesce(func.sum(Record.count), 0),
        )
        .join(Report, Report.id == Record.report_id)
        .where(Report.tenant_id == tenant_id)
        .group_by(Record.dkim_eval, Record.spf_eval, Record.disposition)
    )
    if domain_id is not None:
        q = q.where(Report.domain_id == domain_id)
    if since is not None:
        q = q.where(Report.date_begin >= since)

    totals = DispositionTotals()
    for dkim_eval, spf_eval, disp, count in db.execute(q).all():
        c = int(count or 0)
        totals.total += c
        if _aligned(dkim_eval, spf_eval):
            totals.pass_count += c
        else:
            totals.fail_count += c
        if disp == "quarantine":
            totals.quarantine_count += c
        elif disp == "reject":
            totals.reject_count += c
    return totals


def daily_series(db: Session, *, tenant_id: int, domain_id: Optional[int] = None,
                 days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(
            Report.date_begin,
            Record.dkim_eval,
            Record.spf_eval,
            func.coalesce(func.sum(Record.count), 0),
        )
        .join(Report, Report.id == Record.report_id)
        .where(Report.tenant_id == tenant_id, Report.date_begin >= since)
        .group_by(Report.date_begin, Record.dkim_eval, Record.spf_eval)
        .order_by(Report.date_begin)
    )
    if domain_id is not None:
        q = q.where(Report.domain_id == domain_id)

    bucket: dict[str, dict] = {}
    for begin, dkim_eval, spf_eval, count in db.execute(q).all():
        if begin is None:
            continue
        if isinstance(begin, str):
            key = begin[:10]
        else:
            key = begin.strftime("%Y-%m-%d")
        b = bucket.setdefault(key, {"day": key, "pass": 0, "fail": 0})
        c = int(count or 0)
        if _aligned(dkim_eval, spf_eval):
            b["pass"] += c
        else:
            b["fail"] += c
    return sorted(bucket.values(), key=lambda r: r["day"])


def top_sources(db: Session, *, tenant_id: int, domain_id: Optional[int] = None,
                limit: int = 10, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(
            Record.source_ip,
            Record.source_host,
            Record.dkim_eval,
            Record.spf_eval,
            func.coalesce(func.sum(Record.count), 0).label("c"),
        )
        .join(Report, Report.id == Record.report_id)
        .where(Report.tenant_id == tenant_id, Report.date_begin >= since)
        .group_by(Record.source_ip, Record.source_host, Record.dkim_eval, Record.spf_eval)
    )
    if domain_id is not None:
        q = q.where(Report.domain_id == domain_id)

    aggregated: dict[str, dict] = {}
    for ip, host, dkim_eval, spf_eval, count in db.execute(q).all():
        b = aggregated.setdefault(ip, {"ip": ip, "host": host, "total": 0, "pass": 0, "fail": 0})
        if host and not b["host"]:
            b["host"] = host
        c = int(count or 0)
        b["total"] += c
        if _aligned(dkim_eval, spf_eval):
            b["pass"] += c
        else:
            b["fail"] += c
    rows = sorted(aggregated.values(), key=lambda r: r["total"], reverse=True)[:limit]
    for row in rows:
        row["pass_rate"] = round(100.0 * row["pass"] / row["total"], 1) if row["total"] else 0.0
    return rows


def classify_top_sources(rows: list[dict], *, mx_ips: Optional[set] = None,
                         allowlist_ips: Optional[set] = None) -> list[dict]:
    """Apply source classification to a list returned from top_sources()."""
    from .source_classifier import classify_source, category_meta
    mx_ips = mx_ips or set()
    allowlist_ips = allowlist_ips or set()
    out = []
    for r in rows:
        c = classify_source(
            ip=r["ip"],
            hostname=r.get("host"),
            pass_count=r.get("pass", 0),
            fail_count=r.get("fail", 0),
            total_count=r.get("total", 0),
            is_mx_ip=r["ip"] in mx_ips,
            is_in_allowlist=r["ip"] in allowlist_ips,
        )
        c["meta"] = category_meta(c["category"])
        merged = dict(r)
        merged["classification"] = c
        out.append(merged)
    return out


def reseller_overview(db: Session, *, reseller_id: int, days: int = 30) -> dict:
    """KPIs + per-tenant + per-domain rollups for the MSP console."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    tenants = db.execute(
        select(Tenant).where(Tenant.reseller_id == reseller_id).order_by(Tenant.name)
    ).scalars().all()
    tenant_ids = [t.id for t in tenants]
    n_customers = len(tenants)

    if not tenant_ids:
        return {
            "n_customers": 0, "n_domains": 0, "total_messages": 0, "avg_pass_rate": 0.0,
            "tenants": [], "domains": [],
        }

    domains = db.execute(
        select(Domain).where(Domain.tenant_id.in_(tenant_ids)).order_by(Domain.name)
    ).scalars().all()
    n_domains = len(domains)

    rows = db.execute(
        select(Report.tenant_id, Report.domain_id, Record.dkim_eval, Record.spf_eval,
               func.coalesce(func.sum(Record.count), 0))
        .join(Record, Record.report_id == Report.id)
        .where(Report.tenant_id.in_(tenant_ids), Report.date_begin >= since)
        .group_by(Report.tenant_id, Report.domain_id, Record.dkim_eval, Record.spf_eval)
    ).all()

    by_domain: dict[int, dict] = {}
    by_tenant: dict[int, dict] = {}
    total_msg = 0
    total_pass = 0
    for tid, did, dkim, spf, c in rows:
        c = int(c or 0)
        total_msg += c
        if _aligned(dkim, spf):
            total_pass += c
        b = by_domain.setdefault(did, {"total": 0, "pass": 0})
        b["total"] += c
        if _aligned(dkim, spf):
            b["pass"] += c
        bt = by_tenant.setdefault(tid, {"total": 0, "pass": 0})
        bt["total"] += c
        if _aligned(dkim, spf):
            bt["pass"] += c

    last_per_domain: dict[int, datetime] = dict(db.execute(
        select(Report.domain_id, func.max(Report.date_end))
        .where(Report.tenant_id.in_(tenant_ids))
        .group_by(Report.domain_id)
    ).all())

    tenant_rows = []
    for t in tenants:
        b = by_tenant.get(t.id, {"total": 0, "pass": 0})
        rate = round(100.0 * b["pass"] / b["total"], 1) if b["total"] else 0.0
        tenant_rows.append({
            "tenant": t,
            "n_domains": sum(1 for d in domains if d.tenant_id == t.id),
            "total": b["total"], "pass": b["pass"], "pass_rate": rate,
        })

    domain_rows = []
    tenant_by_id = {t.id: t for t in tenants}
    for d in domains:
        b = by_domain.get(d.id, {"total": 0, "pass": 0})
        rate = round(100.0 * b["pass"] / b["total"], 1) if b["total"] else 0.0
        domain_rows.append({
            "domain": d,
            "tenant": tenant_by_id.get(d.tenant_id),
            "total": b["total"], "pass": b["pass"], "pass_rate": rate,
            "last_report": last_per_domain.get(d.id),
        })
    domain_rows.sort(key=lambda r: (r["tenant"].name if r["tenant"] else "", r["domain"].name))

    avg_rate = round(100.0 * total_pass / total_msg, 1) if total_msg else 0.0
    return {
        "n_customers": n_customers,
        "n_domains": n_domains,
        "total_messages": total_msg,
        "avg_pass_rate": avg_rate,
        "tenants": tenant_rows,
        "domains": domain_rows,
    }


def domain_summaries(db: Session, *, tenant_id: int, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    domains = db.execute(
        select(Domain).where(Domain.tenant_id == tenant_id).order_by(Domain.name)
    ).scalars().all()
    out: list[dict] = []
    for d in domains:
        totals = domain_totals(db, tenant_id=tenant_id, domain_id=d.id, since=since)
        last_report = db.execute(
            select(func.max(Report.date_end))
            .where(Report.domain_id == d.id, Report.tenant_id == tenant_id)
        ).scalar()
        spark = sparkline(db, tenant_id=tenant_id, domain_id=d.id, days=14)
        out.append({
            "domain": d,
            "total": totals.total,
            "pass": totals.pass_count,
            "fail": totals.fail_count,
            "quarantine": totals.quarantine_count,
            "reject": totals.reject_count,
            "pass_rate": totals.pass_rate,
            "last_report": last_report,
            "sparkline": spark,
        })
    return out


# --- Sender attribution -------------------------------------------------------

# (regex, friendly label, color) — first match wins
SENDER_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"google[\w.-]*$|\.gmail\.com$"), "Google", "#4285F4"),
    (re.compile(r"microsoft[\w.-]*$|\.outlook\.com$|protection\.outlook\.com$"), "Microsoft 365", "#0078D4"),
    (re.compile(r"mailchimp[\w.-]*$|mcdlv\.net$|mcsv\.net$"), "Mailchimp", "#FFE01B"),
    (re.compile(r"sendgrid[\w.-]*$"), "SendGrid", "#1A82E2"),
    (re.compile(r"klaviyo[\w.-]*$"), "Klaviyo", "#FF7B66"),
    (re.compile(r"amazonses\.com$|\.ses\.amazonaws\.com$"), "Amazon SES", "#FF9900"),
    (re.compile(r"yahoo[\w.-]*$|yahoodns\.net$"), "Yahoo", "#6001D2"),
    (re.compile(r"protonmail\.[\w.-]+$"), "ProtonMail", "#6D4AFF"),
    (re.compile(r"\bspoof[\w.-]*"), "Verdächtig", "#dc2626"),
    (re.compile(r"\bci[-_]"), "CI/Build", "#64748b"),
    (re.compile(r"eigene[-]?server|own[-]?server|self[-]?host"), "Eigene Server", "#0ea5e9"),
]

PALETTE = ["#2563eb", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6",
           "#06b6d4", "#84cc16", "#f43f5e", "#14b8a6", "#a855f7"]


def sender_label(host: Optional[str], ip: str) -> str:
    """Map a reverse-DNS host to a friendly sender label. Falls back to eTLD+1."""
    if host:
        h = host.lower().strip(".")
        for pat, label, _color in SENDER_RULES:
            if pat.search(h):
                return label
        parts = h.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return h
    return f"IP {ip}"


def _sender_color(label: str, fallback_idx: int) -> str:
    for _pat, lab, color in SENDER_RULES:
        if lab == label:
            return color
    return PALETTE[fallback_idx % len(PALETTE)]


def sender_breakdown(db: Session, *, tenant_id: int, domain_id: Optional[int] = None,
                     days: int = 30, limit: int = 8) -> list[dict]:
    """Aggregate volume by sender label. Returns top N senders + 'Andere' bucket."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(Record.source_ip, Record.source_host, Record.dkim_eval, Record.spf_eval,
               func.coalesce(func.sum(Record.count), 0))
        .join(Report, Report.id == Record.report_id)
        .where(Report.tenant_id == tenant_id, Report.date_begin >= since)
        .group_by(Record.source_ip, Record.source_host, Record.dkim_eval, Record.spf_eval)
    )
    if domain_id is not None:
        q = q.where(Report.domain_id == domain_id)

    bucket: dict[str, dict] = {}
    for ip, host, dkim, spf, count in db.execute(q).all():
        label = sender_label(host, ip)
        b = bucket.setdefault(label, {"label": label, "total": 0, "pass": 0, "fail": 0})
        c = int(count or 0)
        b["total"] += c
        if _aligned(dkim, spf):
            b["pass"] += c
        else:
            b["fail"] += c
    rows = sorted(bucket.values(), key=lambda r: r["total"], reverse=True)
    if len(rows) > limit:
        head = rows[:limit]
        rest = rows[limit:]
        head.append({
            "label": "Andere",
            "total": sum(r["total"] for r in rest),
            "pass": sum(r["pass"] for r in rest),
            "fail": sum(r["fail"] for r in rest),
        })
        rows = head
    for i, r in enumerate(rows):
        r["pass_rate"] = round(100.0 * r["pass"] / r["total"], 1) if r["total"] else 0.0
        r["color"] = _sender_color(r["label"], i)
    return rows


def sender_daily_stack(db: Session, *, tenant_id: int, domain_id: Optional[int] = None,
                       days: int = 30, top_n: int = 6) -> dict:
    """Daily volume per top-N sender (rest as 'Andere'). For stacked area chart."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(Report.date_begin, Record.source_ip, Record.source_host,
               func.coalesce(func.sum(Record.count), 0))
        .join(Report, Report.id == Record.report_id)
        .where(Report.tenant_id == tenant_id, Report.date_begin >= since)
        .group_by(Report.date_begin, Record.source_ip, Record.source_host)
        .order_by(Report.date_begin)
    )
    if domain_id is not None:
        q = q.where(Report.domain_id == domain_id)

    # totals per sender (for ranking)
    sender_totals: dict[str, int] = {}
    daily: dict[str, dict[str, int]] = {}
    for begin, ip, host, count in db.execute(q).all():
        if begin is None:
            continue
        day_key = begin.strftime("%Y-%m-%d") if hasattr(begin, "strftime") else str(begin)[:10]
        label = sender_label(host, ip)
        c = int(count or 0)
        sender_totals[label] = sender_totals.get(label, 0) + c
        daily.setdefault(day_key, {})[label] = daily.setdefault(day_key, {}).get(label, 0) + c

    top_senders = [s for s, _ in sorted(sender_totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]]
    days_sorted = sorted(daily.keys())
    series = []
    for i, label in enumerate(top_senders):
        color = _sender_color(label, i)
        data = [daily[d].get(label, 0) for d in days_sorted]
        series.append({"label": label, "data": data, "backgroundColor": color, "borderColor": color})
    # 'Andere' bucket
    other_data = []
    has_other = False
    for d in days_sorted:
        rest = sum(v for k, v in daily[d].items() if k not in top_senders)
        if rest > 0:
            has_other = True
        other_data.append(rest)
    if has_other:
        series.append({"label": "Andere", "data": other_data,
                        "backgroundColor": "#94a3b8", "borderColor": "#94a3b8"})
    return {"labels": days_sorted, "datasets": series}


def sankey_data(db: Session, *, tenant_id: int, domain_id: Optional[int] = None,
                days: int = 30, top_n_senders: int = 6) -> list[dict]:
    """Sankey flow: sender -> alignment (pass/fail) -> disposition.

    Returns list of {from, to, flow} dicts ready for chartjs-chart-sankey.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(Record.source_ip, Record.source_host, Record.dkim_eval, Record.spf_eval,
               Record.disposition, func.coalesce(func.sum(Record.count), 0))
        .join(Report, Report.id == Record.report_id)
        .where(Report.tenant_id == tenant_id, Report.date_begin >= since)
        .group_by(Record.source_ip, Record.source_host, Record.dkim_eval, Record.spf_eval,
                  Record.disposition)
    )
    if domain_id is not None:
        q = q.where(Report.domain_id == domain_id)

    sender_totals: dict[str, int] = {}
    rows = []
    for ip, host, dkim, spf, disp, count in db.execute(q).all():
        label = sender_label(host, ip)
        c = int(count or 0)
        if c <= 0:
            continue
        sender_totals[label] = sender_totals.get(label, 0) + c
        rows.append((label, dkim, spf, disp or "none", c))
    top = {s for s, _ in sorted(sender_totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n_senders]}

    # Aggregate flows
    flows_a: dict[tuple[str, str], int] = {}  # sender -> alignment
    flows_b: dict[tuple[str, str], int] = {}  # alignment -> disposition
    for label, dkim, spf, disp, c in rows:
        sender_node = label if label in top else "Andere"
        alignment = "Aligned" if _aligned(dkim, spf) else "Not aligned"
        flows_a[(sender_node, alignment)] = flows_a.get((sender_node, alignment), 0) + c
        disp_node = {"none": "Delivered", "quarantine": "Quarantined", "reject": "Rejected"}.get(disp, disp.title())
        flows_b[(alignment, disp_node)] = flows_b.get((alignment, disp_node), 0) + c

    out = []
    for (a, b), v in flows_a.items():
        out.append({"from": a, "to": b, "flow": v})
    for (a, b), v in flows_b.items():
        out.append({"from": a, "to": b, "flow": v})
    return out


def calendar_heatmap(db: Session, *, tenant_id: int, domain_id: Optional[int] = None,
                     days: int = 84) -> dict:
    """GitHub-style calendar heatmap: per-day volume + pass-rate, last N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(Report.date_begin, Record.dkim_eval, Record.spf_eval,
               func.coalesce(func.sum(Record.count), 0))
        .join(Record, Record.report_id == Report.id)
        .where(Report.tenant_id == tenant_id, Report.date_begin >= since)
        .group_by(Report.date_begin, Record.dkim_eval, Record.spf_eval)
    )
    if domain_id is not None:
        q = q.where(Report.domain_id == domain_id)
    rows = db.execute(q).all()
    bucket: dict[str, dict] = {}
    for begin, dkim, spf, c in rows:
        if begin is None:
            continue
        key = begin.strftime("%Y-%m-%d") if hasattr(begin, "strftime") else str(begin)[:10]
        b = bucket.setdefault(key, {"day": key, "total": 0, "pass": 0})
        cnt = int(c or 0)
        b["total"] += cnt
        if _aligned(dkim, spf):
            b["pass"] += cnt
    # build grid: weeks x weekdays (Mon=0..Sun=6)
    today = datetime.now(timezone.utc).date()
    grid_days = []
    max_total = max((b["total"] for b in bucket.values()), default=0)
    for offset in range(days, -1, -1):
        d = today - timedelta(days=offset)
        key = d.strftime("%Y-%m-%d")
        b = bucket.get(key, {"day": key, "total": 0, "pass": 0})
        intensity = 0
        if max_total > 0 and b["total"] > 0:
            ratio = b["total"] / max_total
            if ratio < 0.1: intensity = 1
            elif ratio < 0.33: intensity = 2
            elif ratio < 0.66: intensity = 3
            else: intensity = 4
        pass_rate = round(100.0 * b["pass"] / b["total"], 1) if b["total"] else None
        grid_days.append({
            "date": key, "weekday": d.weekday(),  # 0=Mon
            "total": b["total"], "pass_rate": pass_rate, "intensity": intensity,
        })
    return {"days": grid_days, "max": max_total}


def sparkline(db: Session, *, tenant_id: int, domain_id: int, days: int = 14) -> list[int]:
    """Return a small per-day total volume series for inline sparkline."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(Report.date_begin, func.coalesce(func.sum(Record.count), 0))
        .join(Record, Record.report_id == Report.id)
        .where(Report.tenant_id == tenant_id, Report.domain_id == domain_id,
               Report.date_begin >= since)
        .group_by(Report.date_begin)
        .order_by(Report.date_begin)
    ).all()
    bucket: dict[str, int] = {}
    for begin, c in rows:
        if begin is None:
            continue
        key = begin.strftime("%Y-%m-%d") if hasattr(begin, "strftime") else str(begin)[:10]
        bucket[key] = bucket.get(key, 0) + int(c or 0)
    return [bucket[d] for d in sorted(bucket.keys())]
