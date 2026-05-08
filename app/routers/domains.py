import csv
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..advisor import evaluate as evaluate_advice
from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin, require_user
from ..dns_utils import has_dmarc_record, verification_present
from ..models import Domain, DomainTag, IpAllowlist, Tag, User
from ..security import make_token
from ..stats import (daily_series, domain_totals, sankey_data, sender_breakdown,
                       sender_daily_stack, top_sources)
from ..templating import render

router = APIRouter(prefix="/domains")


def _get_domain(db: Session, domain_id: int, tid: int) -> Domain:
    domain = db.execute(
        select(Domain)
        .options(selectinload(Domain.tenant))
        .where(Domain.id == domain_id)
    ).scalars().first()
    if not domain or domain.tenant_id != tid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")
    return domain


@router.get("")
def list_domains(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    domains = db.execute(
        select(Domain).where(Domain.tenant_id == effective_tenant_id(request, user)).order_by(Domain.name)
    ).scalars().all()
    # tags per domain
    tags_by_domain: dict[int, list[Tag]] = {}
    rows = db.execute(
        select(DomainTag.domain_id, Tag)
        .join(Tag, Tag.id == DomainTag.tag_id)
        .where(Tag.tenant_id == effective_tenant_id(request, user))
    ).all()
    for did, tag in rows:
        tags_by_domain.setdefault(did, []).append(tag)
    all_tags = db.execute(
        select(Tag).where(Tag.tenant_id == effective_tenant_id(request, user)).order_by(Tag.name)
    ).scalars().all()
    return render(request, "domains.html", user=user, tenant=effective_tenant(request, user, db),
                  domains=domains, tags_by_domain=tags_by_domain, all_tags=all_tags,
                  active="domains")


@router.post("")
def create_domain(
    request: Request,
    name: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = name.strip().lower().rstrip(".")
    if not name or "." not in name:
        raise HTTPException(status_code=400, detail="Ungültiger Domainname")
    existing = db.execute(
        select(Domain).where(Domain.tenant_id == effective_tenant_id(request, user), Domain.name == name)
    ).scalars().first()
    if existing:
        return RedirectResponse(f"/domains/{existing.id}", status_code=303)
    domain = Domain(tenant_id=effective_tenant_id(request, user), name=name, verification_token=make_token())
    db.add(domain)
    audit.record(db, user=user, action="domain.create", target_type="domain", target_id=name,
                 ip=request.client.host if request.client else None)
    db.commit()
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)


@router.get("/blacklist")
def blacklist_overview(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Tenant-wide overview of all blacklist checks across all domains.

    Must be defined BEFORE /{domain_id} or FastAPI matches "blacklist" as a
    domain_id and returns 422.
    """
    from .. import models as _m
    from sqlalchemy import desc
    tid = effective_tenant_id(request, user)
    domains = db.execute(
        select(Domain).where(Domain.tenant_id == tid).order_by(Domain.name)
    ).scalars().all()

    # latest BlacklistCheck per (domain_id, ip)
    by_domain: dict[int, list] = {}
    for d in domains:
        rows = db.execute(
            select(_m.BlacklistCheck)
            .where(_m.BlacklistCheck.domain_id == d.id)
            .order_by(desc(_m.BlacklistCheck.checked_at))
            .limit(80)
        ).scalars().all()
        seen: set[str] = set()
        latest = []
        for r in rows:
            if r.ip in seen:
                continue
            seen.add(r.ip)
            latest.append(r)
        by_domain[d.id] = latest

    # totals
    total_ips = sum(len(v) for v in by_domain.values())
    listed_ips = sum(1 for v in by_domain.values() for c in v if c.severity > 0)
    critical_ips = sum(1 for v in by_domain.values() for c in v if c.severity >= 3)

    return render(
        request,
        "blacklist_overview.html",
        user=user,
        tenant=effective_tenant(request, user, db),
        domains=domains,
        by_domain=by_domain,
        total_ips=total_ips,
        listed_ips=listed_ips,
        critical_ips=critical_ips,
        active="blacklist",
    )


@router.post("/blacklist/run-all")
def blacklist_run_all(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Run blacklist scans across all domains in tenant scope."""
    from ..blacklist_job import check_domain
    tid = effective_tenant_id(request, user)
    domains = db.execute(select(Domain).where(Domain.tenant_id == tid)).scalars().all()
    totals = {"checked": 0, "listed": 0, "alerted": 0}
    for d in domains:
        try:
            stats = check_domain(db, d)
            for k in totals: totals[k] += stats[k]
        except Exception:  # noqa: BLE001
            pass
    request.session["flash"] = (f"Blacklist-Scan fertig: {len(domains)} Domains · "
                                f"{totals['checked']} IPs · {totals['listed']} gelistet · "
                                f"{totals['alerted']} neue Alerts.")
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/domains/blacklist", status_code=303)


@router.get("/{domain_id}")
def domain_detail(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    totals = domain_totals(db, tenant_id=effective_tenant_id(request, user), domain_id=domain.id)
    series = daily_series(db, tenant_id=effective_tenant_id(request, user), domain_id=domain.id, days=30)
    sources = top_sources(db, tenant_id=effective_tenant_id(request, user), domain_id=domain.id, days=30, limit=20)
    senders = sender_breakdown(db, tenant_id=effective_tenant_id(request, user), domain_id=domain.id, days=30)
    sender_stack = sender_daily_stack(db, tenant_id=effective_tenant_id(request, user), domain_id=domain.id, days=30)
    sankey = sankey_data(db, tenant_id=effective_tenant_id(request, user), domain_id=domain.id, days=30)
    advice = evaluate_advice(db, domain)
    allowlist = db.execute(
        select(IpAllowlist).where(IpAllowlist.domain_id == domain.id).order_by(IpAllowlist.created_at.desc())
    ).scalars().all()
    domain_tags = db.execute(
        select(Tag).join(DomainTag, DomainTag.tag_id == Tag.id)
        .where(DomainTag.domain_id == domain.id, Tag.tenant_id == effective_tenant_id(request, user))
    ).scalars().all()
    all_tags = db.execute(
        select(Tag).where(Tag.tenant_id == effective_tenant_id(request, user)).order_by(Tag.name)
    ).scalars().all()
    allowed_ips = {a.ip_or_cidr for a in allowlist}
    # Classify sources (after allowlist is loaded)
    from ..stats import classify_top_sources
    from ..dns_utils import lookup_mx
    import socket as _socket
    mx_ips: set[str] = set()
    try:
        for r in (lookup_mx(domain.name).get("records") or []):
            host = r.get("host")
            if host:
                try:
                    for info in _socket.getaddrinfo(host, None, family=_socket.AF_INET):
                        mx_ips.add(info[4][0])
                except (_socket.gaierror, _socket.herror):
                    pass
    except Exception:  # noqa: BLE001
        pass
    sources = classify_top_sources(sources, mx_ips=mx_ips, allowlist_ips=allowed_ips)
    # Latest blacklist check per IP (most recent row per ip)
    from .. import models as _m
    bl_rows = db.execute(
        select(_m.BlacklistCheck)
        .where(_m.BlacklistCheck.domain_id == domain.id)
        .order_by(_m.BlacklistCheck.checked_at.desc())
        .limit(50)
    ).scalars().all()
    seen_bl: set[str] = set()
    blacklist_checks = []
    for r in bl_rows:
        if r.ip in seen_bl:
            continue
        seen_bl.add(r.ip)
        blacklist_checks.append(r)
    # Hetzner DNS / Managed-DMARC context
    from .. import hetzner_dns
    hetzner_zone = hetzner_dns.get_managed_zone_name()
    delegation_target = (hetzner_dns.delegation_target_fqdn(domain.name, hetzner_zone)
                         if hetzner_zone else "")
    return render(
        request,
        "domain_detail.html",
        user=user,
        tenant=effective_tenant(request, user, db),
        domain=domain,
        totals=totals,
        series=series,
        sources=sources,
        senders=senders,
        sender_stack=sender_stack,
        sankey=sankey,
        advice=advice,
        allowlist=allowlist,
        allowed_ips=allowed_ips,
        domain_tags=domain_tags,
        all_tags=all_tags,
        blacklist_checks=blacklist_checks,
        hetzner_configured=hetzner_dns.configured(),
        hetzner_zone=hetzner_zone,
        delegation_target=delegation_target,
        active="domains",
    )


@router.post("/{domain_id}/managed-dmarc/delegation-with-auth")
async def managed_dmarc_delegation_with_auth(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """1-click: anlegen Authorization-Record + Delegation-Record mit user-supplied Policy.

    Kommt aus dem Konfigurator-Wizard auf der Domain-Detail-Seite. Form-Field `policy`
    enthält den vollen DMARC-String (live im Wizard zusammengeklickt).
    """
    from .. import hetzner_dns
    from datetime import datetime, timezone
    form = await request.form()
    policy = (form.get("policy") or "").strip()
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    if not hetzner_dns.configured():
        request.session["flash"] = "Hetzner DNS nicht konfiguriert."
        return RedirectResponse(f"/domains/{domain.id}", status_code=303)
    if not policy or "v=DMARC1" not in policy:
        request.session["flash"] = "Policy fehlt oder ungültig (muss mit v=DMARC1 beginnen)."
        return RedirectResponse(f"/domains/{domain.id}", status_code=303)
    zone_name = hetzner_dns.get_managed_zone_name()
    auth_name = hetzner_dns.authorization_record_name(domain.name, zone_name)
    deleg_name = hetzner_dns.delegation_record_name(domain.name, zone_name)
    try:
        with hetzner_dns.get_client() as cli:
            zone = cli.find_zone(zone_name)
            if not zone:
                request.session["flash"] = f"Zone '{zone_name}' nicht gefunden."
                return RedirectResponse(f"/domains/{domain.id}", status_code=303)
            cli.upsert_record(zone_name, name=auth_name, rtype="TXT", value="v=DMARC1")
            cli.upsert_record(zone_name, name=deleg_name, rtype="TXT", value=policy)
        now = datetime.now(timezone.utc)
        domain.auth_record_managed = True
        domain.auth_record_at = now
        domain.managed_dmarc = True
        domain.managed_policy = policy
        domain.managed_at = now
        db.commit()
        request.session["flash"] = ("✓ Managed-DMARC eingerichtet mit deiner Policy. "
                                    "Setze jetzt den CNAME beim Kunden — wir prüfen automatisch.")
    except Exception as e:  # noqa: BLE001
        request.session["flash"] = f"Hetzner-API-Fehler: {e}"
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)


@router.post("/{domain_id}/managed-dmarc/setup")
def managed_dmarc_setup_oneclick(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """1-click setup: anlegen Authorization-Record + Delegation-Record mit Default-Policy.

    Default-Policy = `v=DMARC1; p=none; rua=mailto:dmarc@<our-zone>; pct=100`
    (Monitoring-Modus). Kann später per UI verschärft werden.
    """
    from .. import hetzner_dns
    from datetime import datetime, timezone
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    if not hetzner_dns.configured():
        request.session["flash"] = "Hetzner DNS nicht konfiguriert."
        return RedirectResponse(f"/domains/{domain.id}", status_code=303)
    zone_name = hetzner_dns.get_managed_zone_name()
    auth_name = hetzner_dns.authorization_record_name(domain.name, zone_name)
    deleg_name = hetzner_dns.delegation_record_name(domain.name, zone_name)
    default_policy = f"v=DMARC1; p=none; rua=mailto:dmarc@{zone_name}; pct=100"
    try:
        with hetzner_dns.get_client() as cli:
            zone = cli.find_zone(zone_name)
            if not zone:
                request.session["flash"] = f"Zone '{zone_name}' nicht gefunden."
                return RedirectResponse(f"/domains/{domain.id}", status_code=303)
            cli.upsert_record(zone_name, name=auth_name, rtype="TXT", value="v=DMARC1")
            cli.upsert_record(zone_name, name=deleg_name, rtype="TXT", value=default_policy)
        now = datetime.now(timezone.utc)
        domain.auth_record_managed = True
        domain.auth_record_at = now
        domain.managed_dmarc = True
        domain.managed_policy = default_policy
        domain.managed_at = now
        db.commit()
        request.session["flash"] = ("✓ Managed-DMARC eingerichtet. Setze jetzt den CNAME "
                                    "beim Kunden — wir prüfen automatisch ob er da ist.")
    except Exception as e:  # noqa: BLE001
        request.session["flash"] = f"Hetzner-API-Fehler: {e}"
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)


@router.get("/{domain_id}/managed-dmarc/check-cname")
def managed_dmarc_check_cname(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """JSON: ist der Kunden-CNAME _dmarc.<domain> CNAME <our-target> gesetzt?

    Nutzt frisch instanziierten Resolver mit Public-DNS (1.1.1.1, 8.8.8.8) statt
    System-Default — umgeht ggf. lokalen ISP/Router-Cache und sieht schneller
    DNS-Änderungen die der User gerade gesetzt hat.
    """
    from .. import hetzner_dns
    import dns.exception, dns.resolver
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    zone_name = hetzner_dns.get_managed_zone_name()
    expected = hetzner_dns.delegation_target_fqdn(domain.name, zone_name).rstrip(".") + "."
    qname = f"_dmarc.{domain.name}"
    from fastapi.responses import JSONResponse

    # Frischer Resolver pro Aufruf — kein Cache-State zwischen Requests
    fresh = dns.resolver.Resolver(configure=False)
    fresh.nameservers = ["1.1.1.1", "1.0.0.1", "8.8.8.8"]
    fresh.lifetime = 5.0
    fresh.timeout = 4.0

    try:
        answers = fresh.resolve(qname, "CNAME", lifetime=5.0)
        targets = [str(r.target).lower() for r in answers]
        if any(t.rstrip(".") + "." == expected.lower() for t in targets):
            return JSONResponse({"ok": True, "status": "active",
                                 "msg": f"CNAME zeigt korrekt auf {expected}"})
        return JSONResponse({"ok": False, "status": "mismatch",
                             "msg": f"CNAME existiert, zeigt aber auf {targets[0] if targets else '?'}",
                             "expected": expected})
    except dns.resolver.NXDOMAIN:
        return JSONResponse({"ok": False, "status": "missing",
                             "msg": f"_dmarc.{domain.name} ist nicht gesetzt", "expected": expected})
    except dns.resolver.NoAnswer:
        try:
            fresh.resolve(qname, "TXT", lifetime=3.0)
            return JSONResponse({"ok": False, "status": "txt_instead",
                                 "msg": "TXT-Record existiert (alter DMARC-Eintrag) — bitte durch CNAME ersetzen.",
                                 "expected": expected})
        except Exception:  # noqa: BLE001
            return JSONResponse({"ok": False, "status": "no_record",
                                 "msg": "Kein DMARC-Eintrag", "expected": expected})
    except (dns.exception.Timeout, dns.resolver.NoNameservers) as e:
        return JSONResponse({"ok": False, "status": "dns_error",
                             "msg": f"DNS-Fehler: {e}"})


@router.post("/{domain_id}/managed-dmarc/auth-record")
def managed_dmarc_create_auth_record(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Create the External-Destination-Authorization record in our managed zone.

    Schreibt: `<kundedomain>._report._dmarc.<our-zone>` TXT "v=DMARC1"
    Damit dürfen wir RUA-Reports für die Kunden-Domain empfangen.
    """
    from .. import hetzner_dns
    from datetime import datetime, timezone
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    if not hetzner_dns.configured():
        request.session["flash"] = "Hetzner DNS nicht konfiguriert (HETZNER_DNS_TOKEN/ZONE in /admin/system setzen)."
        return RedirectResponse(f"/domains/{domain.id}", status_code=303)
    zone_name = hetzner_dns.get_managed_zone_name()
    name = hetzner_dns.authorization_record_name(domain.name, zone_name)
    try:
        with hetzner_dns.get_client() as cli:
            zone = cli.find_zone(zone_name)
            if not zone:
                request.session["flash"] = f"Zone '{zone_name}' bei Hetzner nicht gefunden — stimmt der Name?"
                return RedirectResponse(f"/domains/{domain.id}", status_code=303)
            cli.upsert_record(zone_name, name=name, rtype="TXT", value="v=DMARC1")
        domain.auth_record_managed = True
        domain.auth_record_at = datetime.now(timezone.utc)
        db.commit()
        request.session["flash"] = f"Authorization-Record angelegt: {name}.{zone_name} → \"v=DMARC1\""
    except Exception as e:  # noqa: BLE001
        request.session["flash"] = f"Hetzner-API-Fehler: {e}"
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)


@router.post("/{domain_id}/managed-dmarc/auth-record/remove")
def managed_dmarc_remove_auth_record(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Remove the External-Destination-Authorization record."""
    from .. import hetzner_dns
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    if not hetzner_dns.configured():
        return RedirectResponse(f"/domains/{domain.id}", status_code=303)
    zone_name = hetzner_dns.get_managed_zone_name()
    name = hetzner_dns.authorization_record_name(domain.name, zone_name)
    try:
        with hetzner_dns.get_client() as cli:
            cli.delete_record_by_name(zone_name, name=name, rtype="TXT")
        domain.auth_record_managed = False
        domain.auth_record_at = None
        db.commit()
        request.session["flash"] = f"Authorization-Record entfernt: {name}.{zone_name}"
    except Exception as e:  # noqa: BLE001
        request.session["flash"] = f"Hetzner-API-Fehler: {e}"
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)


@router.post("/{domain_id}/managed-dmarc/delegation")
async def managed_dmarc_delegation_toggle(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Activate (or update) CNAME-delegation: we host the DMARC policy.

    Form-fields: policy_string ("v=DMARC1; p=quarantine; …"), or empty to disable.
    """
    from .. import hetzner_dns
    from datetime import datetime, timezone
    form = await request.form()
    policy = (form.get("policy") or "").strip()
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    if not hetzner_dns.configured():
        request.session["flash"] = "Hetzner DNS nicht konfiguriert."
        return RedirectResponse(f"/domains/{domain.id}", status_code=303)
    zone_name = hetzner_dns.get_managed_zone_name()
    name = hetzner_dns.delegation_record_name(domain.name, zone_name)
    try:
        with hetzner_dns.get_client() as cli:
            zone = cli.find_zone(zone_name)
            if not zone:
                request.session["flash"] = f"Zone '{zone_name}' nicht gefunden."
                return RedirectResponse(f"/domains/{domain.id}", status_code=303)
            if policy:
                cli.upsert_record(zone_name, name=name, rtype="TXT", value=policy)
                domain.managed_dmarc = True
                domain.managed_policy = policy
                domain.managed_at = datetime.now(timezone.utc)
                request.session["flash"] = f"Managed-DMARC aktiv: {name}.{zone_name} → {policy[:60]}…"
            else:
                cli.delete_record_by_name(zone_name, name=name, rtype="TXT")
                domain.managed_dmarc = False
                domain.managed_policy = None
                domain.managed_at = None
                request.session["flash"] = f"Managed-DMARC deaktiviert."
        db.commit()
    except Exception as e:  # noqa: BLE001
        request.session["flash"] = f"Hetzner-API-Fehler: {e}"
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)


@router.post("/{domain_id}/blacklist-check")
def blacklist_check_now(
    domain_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Run an on-demand blacklist scan for this domain."""
    from ..blacklist_job import check_domain
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    stats = check_domain(db, domain)
    request.session["flash"] = (
        f"Blacklist-Scan: {stats['checked']} IPs geprüft · "
        f"{stats['listed']} gelistet · {stats['alerted']} neue Alerts."
    )
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)


@router.post("/{domain_id}/verify")
def verify_domain(
    domain_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    has_dmarc = has_dmarc_record(domain.name)
    has_token = verification_present(domain.name, domain.verification_token)
    if has_token and domain.verified_at is None:
        from datetime import datetime, timezone
        domain.verified_at = datetime.now(timezone.utc)
        audit.record(db, user=user, action="domain.verify", target_type="domain",
                     target_id=domain.name, ip=request.client.host if request.client else None)
        db.commit()
    return render(
        request,
        "_verify_result.html",
        domain=domain,
        has_dmarc=has_dmarc,
        has_token=has_token,
    )


@router.post("/{domain_id}/delete")
def delete_domain(
    domain_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    audit.record(db, user=user, action="domain.delete", target_type="domain",
                 target_id=domain.name, ip=request.client.host if request.client else None)
    db.delete(domain)
    db.commit()
    return RedirectResponse("/domains", status_code=303)


# --- Bulk import ---------------------------------------------------------------
@router.post("/import")
async def bulk_import(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    raw = (await file.read()).decode("utf-8", errors="replace")
    candidates: list[str] = []
    # try CSV first (column 'name' or first column)
    try:
        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)
        if rows:
            header = [h.strip().lower() for h in rows[0]]
            if "name" in header or "domain" in header:
                idx = header.index("name") if "name" in header else header.index("domain")
                for r in rows[1:]:
                    if r and r[idx].strip():
                        candidates.append(r[idx].strip())
            else:
                for r in rows:
                    if r and r[0].strip():
                        candidates.append(r[0].strip())
    except csv.Error:
        candidates = [line.strip() for line in raw.splitlines() if line.strip()]

    added = 0
    skipped = 0
    invalid = 0
    seen: set[str] = set()
    for name in candidates:
        name = name.strip().lower().rstrip(".")
        if not name or "." not in name or " " in name:
            invalid += 1
            continue
        if name in seen:
            skipped += 1
            continue
        seen.add(name)
        existing = db.execute(
            select(Domain).where(Domain.tenant_id == effective_tenant_id(request, user), Domain.name == name)
        ).scalars().first()
        if existing:
            skipped += 1
            continue
        db.add(Domain(tenant_id=effective_tenant_id(request, user), name=name, verification_token=make_token()))
        added += 1
    audit.record(db, user=user, action="domain.bulk_import", target_type="domains",
                 details={"added": added, "skipped": skipped, "invalid": invalid},
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {
        "kind": "ok" if added else "warn",
        "text": f"Import: {added} angelegt, {skipped} schon vorhanden, {invalid} ungültig.",
    }
    return RedirectResponse("/domains", status_code=303)


# --- Allowlist (per domain) ----------------------------------------------------
@router.post("/{domain_id}/allowlist")
def add_allow(
    domain_id: int,
    request: Request,
    ip_or_cidr: str = Form(...),
    label: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    ip_or_cidr = ip_or_cidr.strip()
    if not ip_or_cidr:
        raise HTTPException(status_code=400, detail="IP fehlt")
    existing = db.execute(
        select(IpAllowlist).where(IpAllowlist.domain_id == domain.id, IpAllowlist.ip_or_cidr == ip_or_cidr)
    ).scalars().first()
    if existing:
        return RedirectResponse(f"/domains/{domain.id}#allowlist", status_code=303)
    db.add(IpAllowlist(tenant_id=effective_tenant_id(request, user), domain_id=domain.id,
                        ip_or_cidr=ip_or_cidr, label=(label.strip() or None)))
    audit.record(db, user=user, action="allowlist.add", target_type="domain",
                 target_id=domain.name, details={"ip": ip_or_cidr},
                 ip=request.client.host if request.client else None)
    db.commit()
    return RedirectResponse(f"/domains/{domain.id}#allowlist", status_code=303)


@router.post("/{domain_id}/allowlist/{entry_id}/delete")
def del_allow(
    domain_id: int,
    entry_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    entry = db.get(IpAllowlist, entry_id)
    if not entry or entry.domain_id != domain.id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    audit.record(db, user=user, action="allowlist.remove", target_type="domain",
                 target_id=domain.name, details={"ip": entry.ip_or_cidr},
                 ip=request.client.host if request.client else None)
    db.delete(entry)
    db.commit()
    return RedirectResponse(f"/domains/{domain.id}#allowlist", status_code=303)


# --- Tags ----------------------------------------------------------------------
@router.post("/{domain_id}/tag/{tag_id}/toggle")
def toggle_tag(
    domain_id: int,
    tag_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    domain = _get_domain(db, domain_id, effective_tenant_id(request, user))
    tag = db.get(Tag, tag_id)
    if not tag or tag.tenant_id != effective_tenant_id(request, user):
        raise HTTPException(status_code=404, detail="Tag not found")
    link = db.execute(
        select(DomainTag).where(DomainTag.domain_id == domain.id, DomainTag.tag_id == tag.id)
    ).scalars().first()
    if link:
        db.delete(link)
        action = "domain.tag.remove"
    else:
        db.add(DomainTag(domain_id=domain.id, tag_id=tag.id))
        action = "domain.tag.add"
    audit.record(db, user=user, action=action, target_type="domain", target_id=domain.name,
                 details={"tag": tag.name}, ip=request.client.host if request.client else None)
    db.commit()
    return RedirectResponse(f"/domains/{domain.id}", status_code=303)
