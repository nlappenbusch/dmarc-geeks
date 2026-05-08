"""Compute the onboarding checklist for a tenant."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ApiKey, Domain, Mailbox, Report, Tenant


@dataclass
class CheckItem:
    key: str
    title: str
    hint: str
    done: bool
    cta_label: str
    cta_href: str
    optional: bool = False


@dataclass
class Checklist:
    items: list[CheckItem]

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.items if i.done and not i.optional)

    @property
    def required_count(self) -> int:
        return sum(1 for i in self.items if not i.optional)

    @property
    def percent(self) -> int:
        if self.required_count == 0:
            return 100
        return int(round(100 * self.done_count / self.required_count))

    @property
    def all_done(self) -> bool:
        return self.done_count == self.required_count


def compute(db: Session, tenant: Tenant) -> Checklist:
    has_domain = db.execute(
        select(func.count(Domain.id)).where(Domain.tenant_id == tenant.id)
    ).scalar_one() > 0

    verified_domain = db.execute(
        select(func.count(Domain.id)).where(
            Domain.tenant_id == tenant.id, Domain.verified_at.is_not(None)
        )
    ).scalar_one() > 0

    has_mailbox_or_report = (
        db.execute(select(func.count(Mailbox.id)).where(Mailbox.tenant_id == tenant.id)).scalar_one() > 0
        or db.execute(select(func.count(Report.id)).where(Report.tenant_id == tenant.id)).scalar_one() > 0
    )

    has_data = db.execute(
        select(func.count(Report.id)).where(Report.tenant_id == tenant.id)
    ).scalar_one() > 0

    has_api_key = db.execute(
        select(func.count(ApiKey.id)).where(
            ApiKey.tenant_id == tenant.id, ApiKey.revoked_at.is_(None)
        )
    ).scalar_one() > 0

    items = [
        CheckItem(
            key="domain",
            title="Erste Domain anlegen",
            hint="Trage die Domain ein, deren Mails du beobachten willst.",
            done=has_domain,
            cta_label="Domain anlegen",
            cta_href="/domains",
        ),
        CheckItem(
            key="dns",
            title="DMARC-DNS-Record + Verifikation",
            hint="DMARC-Policy mit rua=mailto:… ins DNS, dann hier verifizieren.",
            done=verified_domain,
            cta_label="DNS-Setup ansehen",
            cta_href="/help#domain-rua",
        ),
        CheckItem(
            key="ingest",
            title="Reports einsammeln",
            hint="Mailbox per IMAP anbinden oder ersten Report manuell hochladen.",
            done=has_mailbox_or_report,
            cta_label="Mailbox anbinden",
            cta_href="/mailboxes",
        ),
        CheckItem(
            key="data",
            title="Erster Report importiert",
            hint="Sobald Reports kommen, siehst du hier dein Dashboard.",
            done=has_data,
            cta_label="Status prüfen",
            cta_href="/reports",
        ),
        CheckItem(
            key="api",
            title="API-Key erstellen (optional)",
            hint="Für Automation und Webhooks.",
            done=has_api_key,
            cta_label="API-Keys verwalten",
            cta_href="/api-keys",
            optional=True,
        ),
    ]
    return Checklist(items=items)
