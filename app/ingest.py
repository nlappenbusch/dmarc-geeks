"""Persisting parsed DMARC reports into the database."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .dns_utils import reverse_lookup
from .models import AuthResult, Domain, IngestLog, Record, Report
from .parser import ParsedReport, parse_payload, DmarcParseError
from .security import make_token

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    status: str  # ok, dup, error, ignored
    message: str = ""
    report_id: Optional[int] = None
    parsed: Optional[ParsedReport] = None


def _find_domain(db: Session, tenant_id: Optional[int], policy_domain: str,
                  reseller_id: Optional[int] = None) -> Optional[Domain]:
    q = select(Domain).where(Domain.name == policy_domain.lower())
    if tenant_id is not None:
        q = q.where(Domain.tenant_id == tenant_id)
    elif reseller_id is not None:
        # Restrict to tenants under this reseller
        from .models import Tenant
        sub = select(Tenant.id).where(Tenant.reseller_id == reseller_id).scalar_subquery()
        q = q.where(Domain.tenant_id.in_(sub))
    return db.execute(q).scalars().first()


def _ensure_domain(db: Session, tenant_id: int, policy_domain: str, auto_create: bool) -> Optional[Domain]:
    name = policy_domain.lower().strip()
    if not name:
        return None
    domain = _find_domain(db, tenant_id, name)
    if domain or not auto_create:
        return domain
    domain = Domain(
        tenant_id=tenant_id,
        name=name,
        verification_token=make_token(),
    )
    db.add(domain)
    db.flush()
    return domain


def _persist(db: Session, domain: Domain, parsed: ParsedReport, *, with_ptr: bool) -> Report:
    report = Report(
        tenant_id=domain.tenant_id,
        domain_id=domain.id,
        org_name=parsed.org_name,
        org_email=parsed.org_email,
        org_extra_contact=parsed.org_extra_contact,
        external_report_id=parsed.external_report_id,
        date_begin=parsed.date_begin,
        date_end=parsed.date_end,
        policy_domain=parsed.policy_domain,
        policy_adkim=parsed.policy_adkim,
        policy_aspf=parsed.policy_aspf,
        policy_p=parsed.policy_p,
        policy_sp=parsed.policy_sp,
        policy_pct=parsed.policy_pct,
        policy_fo=parsed.policy_fo,
        raw_xml=parsed.raw_xml,
    )
    db.add(report)
    db.flush()

    for pr in parsed.records:
        rec = Record(
            report_id=report.id,
            tenant_id=domain.tenant_id,
            source_ip=pr.source_ip,
            source_host=reverse_lookup(pr.source_ip) if with_ptr else None,
            count=pr.count,
            disposition=pr.disposition,
            dkim_eval=pr.dkim_eval,
            spf_eval=pr.spf_eval,
            reason_type=pr.reason_type,
            reason_comment=pr.reason_comment,
            header_from=pr.header_from,
            envelope_from=pr.envelope_from,
            envelope_to=pr.envelope_to,
        )
        db.add(rec)
        db.flush()
        for ar in pr.auth_results:
            db.add(
                AuthResult(
                    record_id=rec.id,
                    auth_type=ar.auth_type,
                    domain=ar.domain,
                    selector=ar.selector,
                    result=ar.result,
                    scope=ar.scope,
                )
            )
    return report


def ingest_parsed(
    db: Session,
    parsed: ParsedReport,
    *,
    tenant_id: Optional[int],
    auto_create_domain: bool,
    source: str = "upload",
    filename: Optional[str] = None,
    reseller_id: Optional[int] = None,
) -> IngestResult:
    settings = get_settings()

    # duplicate check (org_email + external_report_id is unique per spec)
    existing = db.execute(
        select(Report).where(
            Report.org_email == parsed.org_email,
            Report.external_report_id == parsed.external_report_id,
        )
    ).scalars().first()
    if existing:
        result = IngestResult("dup", f"already imported (report id={existing.id})", existing.id, parsed)
        db.add(IngestLog(tenant_id=tenant_id, source=source, filename=filename,
                         status="dup", message=result.message, report_id=existing.id))
        return result

    if tenant_id is None and reseller_id is not None:
        # Reseller-Mailbox-Routing: find matching domain across all tenants of this reseller
        domain = _find_domain(db, None, parsed.policy_domain, reseller_id=reseller_id)
        if domain is None:
            msg = (f"reseller mailbox: domain {parsed.policy_domain!r} not registered "
                   f"in any tenant of reseller {reseller_id}")
            db.add(IngestLog(source=source, filename=filename, status="ignored", message=msg))
            return IngestResult("ignored", msg, parsed=parsed)
    elif tenant_id is None:
        # try to match an existing domain across tenants (single-domain owner wins)
        existing_domains = db.execute(
            select(Domain).where(Domain.name == parsed.policy_domain.lower())
        ).scalars().all()
        if len(existing_domains) == 1:
            domain = existing_domains[0]
        else:
            msg = ("no tenant context and policy_domain "
                   f"{parsed.policy_domain!r} matches {len(existing_domains)} domains")
            db.add(IngestLog(source=source, filename=filename, status="ignored", message=msg))
            return IngestResult("ignored", msg, parsed=parsed)
    else:
        domain = _ensure_domain(db, tenant_id, parsed.policy_domain, auto_create=auto_create_domain)
        if domain is None:
            msg = f"domain {parsed.policy_domain!r} not registered for tenant {tenant_id}"
            db.add(IngestLog(tenant_id=tenant_id, source=source, filename=filename,
                             status="ignored", message=msg))
            return IngestResult("ignored", msg, parsed=parsed)

    report = _persist(db, domain, parsed, with_ptr=settings.resolve_ptr)
    db.add(IngestLog(tenant_id=domain.tenant_id, source=source, filename=filename,
                     status="ok", message=f"records={len(parsed.records)}", report_id=report.id))
    # spike alert (best-effort, ignore failures)
    try:
        from .notifications import check_spike
        check_spike(db, tenant_id=domain.tenant_id, domain=domain, parsed_count=len(parsed.records))
    except Exception as e:  # noqa: BLE001
        log.debug("spike check failed: %s", e)
    # webhook (fire-and-forget after commit by caller)
    try:
        from .webhooks import emit as emit_webhook
        emit_webhook(domain.tenant_id, "report.imported",
                     {"report_id": report.id, "domain": domain.name,
                      "records": len(parsed.records)})
    except Exception as e:  # noqa: BLE001
        log.debug("webhook emit failed: %s", e)
    return IngestResult("ok", f"imported {len(parsed.records)} records", report.id, parsed)


def ingest_payload(
    db: Session,
    filename: str,
    data: bytes,
    *,
    tenant_id: Optional[int],
    auto_create_domain: bool,
    source: str = "upload",
    reseller_id: Optional[int] = None,
) -> list[IngestResult]:
    try:
        parsed_list = parse_payload(filename, data)
    except DmarcParseError as e:
        db.add(IngestLog(tenant_id=tenant_id, source=source, filename=filename,
                         status="error", message=str(e)))
        return [IngestResult("error", str(e))]

    results: list[IngestResult] = []
    for parsed in parsed_list:
        results.append(
            ingest_parsed(
                db,
                parsed,
                tenant_id=tenant_id,
                auto_create_domain=auto_create_domain,
                source=source,
                filename=filename,
                reseller_id=reseller_id,
            )
        )
    return results
