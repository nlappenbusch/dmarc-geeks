"""Generate realistic demo data: 3 domains, 30 days of reports, multiple senders.

Run inside a Python env with the app's deps installed and the same DATABASE_URL
the app uses, e.g.:

    python -m scripts.seed_demo

It targets the existing 'Default' tenant. Idempotent: re-running skips domains
that already exist (or you can pass --reset to wipe demo domains first).
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal, Base, engine
from app.models import (AuthResult, Domain, IpAllowlist, Record, Report, Tag,
                          DomainTag, Tenant, TenantSettings)
from app.security import make_token


# fixed RNG for reproducibility
rng = random.Random(42)

# Demo domains with their typical sender mix
DEMOS = [
    {
        "name": "acme-corp.demo",
        "tags": [("Produktion", "#16a34a")],
        "policy": "quarantine",
        "senders": [
            # (label, ip_pool, daily_volume_range, fail_rate)
            ("Google Workspace", ["209.85.220.41", "209.85.220.42", "209.85.166.45"], (800, 1500), 0.005),
            ("Microsoft 365",     ["40.92.40.20", "40.107.220.61", "52.96.110.131"], (300, 700),   0.01),
            ("Mailchimp",         ["198.2.130.10", "205.201.137.12"],                (150, 400),   0.02),
            ("Sendgrid",          ["167.89.123.45", "168.245.20.19"],                (100, 250),   0.015),
            ("Spoofer (Russia)",  ["91.234.99.{}".format(i) for i in range(10, 14)], (5, 25),      1.0),
        ],
    },
    {
        "name": "marketing.demo",
        "tags": [("Marketing", "#d97706")],
        "policy": "none",
        "senders": [
            ("Mailchimp",     ["198.2.130.10", "198.2.130.11", "205.201.137.12"], (1000, 3000), 0.03),
            ("Sendgrid",      ["167.89.123.45", "168.245.20.20"],                  (400, 900),   0.02),
            ("Klaviyo",       ["198.2.180.50"],                                    (200, 600),   0.04),
            ("Eigene Server", ["198.51.100.30"],                                   (50, 120),    0.4),  # broken DKIM
            ("Spoofer",       ["185.220.101.42"],                                  (1, 6),       1.0),
        ],
    },
    {
        "name": "dev-staging.demo",
        "tags": [("Staging", "#64748b")],
        "policy": "none",
        "senders": [
            ("Google Workspace", ["209.85.220.41"],          (5, 30),  0.0),
            ("CI Notifications", ["198.51.100.55"],          (10, 50), 0.6),  # broken SPF
            ("Spoofer",          ["91.234.99.10"],           (1, 4),   1.0),
        ],
    },
]

REPORTERS = [
    ("google.com", "noreply-dmarc-support@google.com"),
    ("Outlook.com", "dmarcreport@microsoft.com"),
    ("Yahoo! Inc.", "dmarchelp@yahooinc.com"),
]


def _ensure_tenant(db) -> Tenant:
    t = db.execute(select(Tenant).where(Tenant.slug == "default")).scalars().first()
    if t is None:
        t = Tenant(name="Default", slug="default")
        db.add(t)
        db.flush()
        db.add(TenantSettings(tenant_id=t.id))
    if t.settings is None:
        db.add(TenantSettings(tenant_id=t.id))
    return t


def _ensure_tag(db, tenant: Tenant, name: str, color: str) -> Tag:
    tag = db.execute(
        select(Tag).where(Tag.tenant_id == tenant.id, Tag.name == name)
    ).scalars().first()
    if tag is None:
        tag = Tag(tenant_id=tenant.id, name=name, color=color)
        db.add(tag)
        db.flush()
    return tag


def _create_domain(db, tenant: Tenant, name: str, tag_specs: list[tuple[str, str]]) -> Domain:
    d = db.execute(
        select(Domain).where(Domain.tenant_id == tenant.id, Domain.name == name)
    ).scalars().first()
    if d is None:
        d = Domain(
            tenant_id=tenant.id,
            name=name,
            verification_token=make_token(),
            verified_at=datetime.now(timezone.utc),  # mark as verified for demo
        )
        db.add(d)
        db.flush()
    for tname, tcolor in tag_specs:
        tag = _ensure_tag(db, tenant, tname, tcolor)
        existing = db.execute(
            select(DomainTag).where(DomainTag.domain_id == d.id, DomainTag.tag_id == tag.id)
        ).scalars().first()
        if not existing:
            db.add(DomainTag(domain_id=d.id, tag_id=tag.id))
    return d


def _gen_reports_for_day(db, domain: Domain, policy: str, senders: list, day: datetime):
    """One report per reporter per day, each with multiple records."""
    for org_name, org_email in REPORTERS:
        report_id_ext = f"demo-{domain.id}-{day.strftime('%Y%m%d')}-{org_email[:4]}"
        existing = db.execute(
            select(Report).where(
                Report.org_email == org_email,
                Report.external_report_id == report_id_ext,
            )
        ).scalars().first()
        if existing:
            continue
        begin = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = begin + timedelta(hours=24)
        rep = Report(
            tenant_id=domain.tenant_id,
            domain_id=domain.id,
            org_name=org_name,
            org_email=org_email,
            external_report_id=report_id_ext,
            date_begin=begin,
            date_end=end,
            policy_domain=domain.name,
            policy_adkim="r",
            policy_aspf="r",
            policy_p=policy,
            policy_sp=policy,
            policy_pct=100,
            received_at=end + timedelta(hours=4),
            raw_xml=None,
        )
        db.add(rep)
        db.flush()
        # Each reporter sees roughly 1/N of the daily volume
        for label, ips, (lo, hi), fail_rate in senders:
            volume = max(0, rng.randint(lo, hi) // len(REPORTERS))
            if volume == 0:
                continue
            # split across IPs of that sender, with some passing and some failing
            ips_in_pool = rng.sample(ips, min(len(ips), max(1, len(ips))))
            for ip in ips_in_pool:
                share = volume // len(ips_in_pool)
                if share == 0:
                    continue
                # split into pass/fail buckets
                fails = int(share * fail_rate)
                passes = share - fails
                for count, dkim, spf, disp in [
                    (passes, "pass", "pass", "none"),
                    (fails, "fail", "fail", policy if policy != "none" else "none"),
                ]:
                    if count <= 0:
                        continue
                    rec = Record(
                        report_id=rep.id, tenant_id=domain.tenant_id,
                        source_ip=ip, source_host=label.lower().replace(" ", "-") + ".example",
                        count=count, disposition=disp,
                        dkim_eval=dkim, spf_eval=spf,
                        header_from=domain.name, envelope_from=domain.name,
                    )
                    db.add(rec)
                    db.flush()
                    db.add(AuthResult(record_id=rec.id, auth_type="dkim",
                                       domain=domain.name, selector="default", result=dkim))
                    db.add(AuthResult(record_id=rec.id, auth_type="spf",
                                       domain=domain.name, result=spf, scope="mfrom"))


def seed_tenant(db, tenant: Tenant, days: int = 30, reset: bool = False) -> dict:
    """Seed demo domains + reports into the given tenant. Idempotent.

    Returns a dict with counts so callers (CLI or web /demo endpoint) can show stats.
    """
    deleted = 0
    if reset:
        for d in db.execute(
            select(Domain).where(Domain.tenant_id == tenant.id, Domain.name.like("%.demo"))
        ).scalars().all():
            db.delete(d)
            deleted += 1
        db.commit()

    domains_seen = []
    for spec in DEMOS:
        d = _create_domain(db, tenant, spec["name"], spec["tags"])
        domains_seen.append(d)
        for label, ips, _, fail_rate in spec["senders"]:
            if fail_rate < 0.5:
                for ip in ips:
                    if not db.execute(select(IpAllowlist).where(
                        IpAllowlist.domain_id == d.id, IpAllowlist.ip_or_cidr == ip
                    )).scalars().first():
                        db.add(IpAllowlist(tenant_id=tenant.id, domain_id=d.id,
                                            ip_or_cidr=ip, label=label))
        db.commit()

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    reports_added = 0
    for spec in DEMOS:
        d = db.execute(
            select(Domain).where(Domain.tenant_id == tenant.id, Domain.name == spec["name"])
        ).scalars().first()
        for n in range(days):
            day = today - timedelta(days=n)
            _gen_reports_for_day(db, d, spec["policy"], spec["senders"], day)
            reports_added += 1
        db.commit()

    return {
        "tenant": tenant.name,
        "domains": len(domains_seen),
        "reports_days": days,
        "deleted_on_reset": deleted,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true",
                    help="Delete demo domains before seeding")
    p.add_argument("--days", type=int, default=30, help="Days of history to generate")
    args = p.parse_args()

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        tenant = _ensure_tenant(db)
        result = seed_tenant(db, tenant, days=args.days, reset=args.reset)
        for spec in DEMOS:
            print(f"  OK {spec['name']}: {args.days} Tage Demo-Daten")
        print(f"\nFertig: {result}")
        print("Login -> Dashboard oeffnen, um die Demo-Daten zu sehen.")


if __name__ == "__main__":
    main()
