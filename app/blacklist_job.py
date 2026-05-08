"""Scheduled job: per domain, run DNSBL checks against MX-IPs and top-sender-IPs,
persist results to the blacklist_checks table, and email an alert when a previously
clean IP turns up on a critical list."""
from __future__ import annotations

import json
import logging
import socket
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import desc, select

from . import notify
from .blacklist import check_ip, delisting_url, severity_for, summary as bl_summary
from .config import get_settings
from .database import SessionLocal
from .dns_utils import lookup_mx
from .models import BlacklistCheck, Domain, Record, Report, Tenant, User

log = logging.getLogger(__name__)

# How many recent sender IPs (besides the MX-IPs) to check per domain.
TOP_SENDERS_TO_CHECK = 3
LOOKBACK_DAYS = 7
# Anti-spam: never send the same event for the same (domain, ip) within this window.
# Protects against flaky DNSBL responses (rate-limits, NXDOMAIN flapping) causing
# a notification loop.
ALERT_COOLDOWN_HOURS = 6


def _resolve_mx_ips(domain: str) -> list[str]:
    """Resolve A-records of MX hostnames. Best-effort, dedup."""
    mx = lookup_mx(domain)
    seen: set[str] = set()
    ips: list[str] = []
    for r in mx.get("records") or []:
        host = r.get("host")
        if not host:
            continue
        try:
            for info in socket.getaddrinfo(host, None, family=socket.AF_INET):
                ip = info[4][0]
                if ip not in seen:
                    seen.add(ip)
                    ips.append(ip)
        except (socket.gaierror, socket.herror):
            continue
    return ips


def _top_sender_ips(db, domain_id: int, limit: int = TOP_SENDERS_TO_CHECK) -> list[str]:
    """Most-frequent source IPs from this domain's recent reports, weighted by mail count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    rows = db.execute(
        select(Record.source_ip, Record.count)
        .join(Report, Report.id == Record.report_id)
        .where(Report.domain_id == domain_id, Report.received_at >= cutoff)
        .where(Record.source_ip.isnot(None))
    ).all()
    counts: Counter[str] = Counter()
    for ip, cnt in rows:
        if ip:
            counts[ip] += int(cnt or 1)
    return [ip for ip, _ in counts.most_common(limit)]


def _last_check_for(db, domain_id: int, ip: str) -> BlacklistCheck | None:
    return db.execute(
        select(BlacklistCheck)
        .where(BlacklistCheck.domain_id == domain_id, BlacklistCheck.ip == ip)
        .order_by(desc(BlacklistCheck.checked_at))
        .limit(1)
    ).scalars().first()


def _recently_alerted(db, domain_id: int, ip: str, event_type: str) -> BlacklistCheck | None:
    """Return the most recent BlacklistCheck row that already triggered an alert
    of `event_type` for this (domain, ip), within the cooldown window. None if
    no such alert was sent within the cooldown.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_HOURS)
    return db.execute(
        select(BlacklistCheck)
        .where(BlacklistCheck.domain_id == domain_id,
               BlacklistCheck.ip == ip,
               BlacklistCheck.alerted_event == event_type,
               BlacklistCheck.alerted_at >= cutoff)
        .order_by(desc(BlacklistCheck.alerted_at))
        .limit(1)
    ).scalars().first()


def _send_alert(tenant: Tenant, domain: Domain, ip: str, role: str, hits: list[dict],
                db, *, event_type: str = "blacklist_alerts") -> None:
    """Email all eligible tenant users when an IP changes blacklist state."""
    settings = get_settings()
    if not settings.smtp_host:
        return
    severity = severity_for(hits)
    severity_label = {3: "KRITISCH", 2: "WARNUNG", 1: "INFO"}.get(severity, "INFO")

    if event_type == "blacklist_resolved":
        subject = f"[DMARC Aggregator] CLEAN: {ip} ist nicht mehr blacklisted ({domain.name})"
        text = (
            f"DNSBL-Entwarnung für Domain {domain.name}\n"
            f"==========================================\n\n"
            f"IP {ip} (Rolle: {role}) ist seit dem letzten Scan von allen Blacklists gelöscht worden.\n\n"
            f"Was du jetzt tun solltest:\n"
            f"- Prüfe ob du die Ursache der Listung wirklich behoben hast — sonst kommt sie zurück.\n"
            f"- Mail-Reputation kann nach einem Listing 1-2 Wochen brauchen um sich zu erholen.\n\n"
            f"---\n"
            f"DMARC Aggregator · automatischer Blacklist-Check"
        )
    else:
        names = ", ".join(sorted({h["name"] for h in hits}))
        subject = f"[DMARC Aggregator] {severity_label}: {ip} blacklisted ({domain.name})"
        # Build per-list delisting links
        delisting_lines = []
        for h in hits:
            url = delisting_url(h.get("zone", ""), ip, "remove")
            delisting_lines.append(f"  • {h['name']:25s}  →  {url}")
        delisting_block = "\n".join(delisting_lines) if delisting_lines else "  (keine spezifischen Links — siehe Sammel-Lookup unten)"

        text = (
            f"DNSBL-Alarm für Domain {domain.name}\n"
            f"==========================================\n\n"
            f"IP {ip} (Rolle: {role}) wurde neu auf {len(hits)} Blacklist(s) gefunden:\n"
            f"  → {names}\n\n"
            f"Schweregrad: {severity_label}\n\n"
            f"Konsequenzen einer Listung:\n"
            f"- Ausgehende Mails von dieser IP werden bei Empfängern mit hoher Wahrscheinlichkeit als Spam markiert oder verworfen\n"
            f"- Bei kritischen Listen (Spamhaus, Barracuda) blockt der Empfänger oft schon beim Connect\n"
            f"- Reputation deiner Domain leidet — DMARC-Pass-Rate kann kippen\n\n"
            f"Was tun:\n"
            f"1. Prüfen ob die IP wirklich unter deiner Kontrolle steht (MX, eigener Mailserver, Marketing-Tool)\n"
            f"2. Bei eigenen IPs: Listing-Grund klären (offene Relays, kompromittierter Account, IP-Wechsel?)\n"
            f"3. Delisting bei jeder gelisteten Liste beantragen — Direkt-Links unten\n"
            f"4. Nach Delisting: Ursache fixen, sonst kommt die IP nach 24h zurück\n\n"
            f"Delisting-Links pro Liste:\n"
            f"{delisting_block}\n\n"
            f"Sammel-Lookup über alle ~140 RBLs:\n"
            f"  https://multirbl.valli.org/lookup/{ip}.html\n\n"
            f"Notification-Einstellungen verwalten:\n"
            f"  /users/me/notifications\n\n"
            f"---\n"
            f"DMARC Aggregator · automatischer Blacklist-Check"
        )

    try:
        sent = notify.notify_tenant(db, tenant.id, event_type, subject, text)
        log.info("Blacklist %s sent to %d users for %s/%s", event_type, sent, domain.name, ip)
    except Exception as e:  # noqa: BLE001
        log.warning("Failed to dispatch blacklist notification: %s", e)


def check_domain(db, domain: Domain) -> dict:
    """Run blacklist checks for one domain. Returns counts: {checked, listed, alerted}."""
    mx_ips = _resolve_mx_ips(domain.name)
    sender_ips = _top_sender_ips(db, domain.id)
    # Dedup with role priority: MX wins
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for ip in mx_ips:
        if ip not in seen:
            seen.add(ip); targets.append((ip, "mx"))
    for ip in sender_ips:
        if ip not in seen:
            seen.add(ip); targets.append((ip, "sender"))

    tenant = db.get(Tenant, domain.tenant_id) if domain.tenant_id else None
    counts = {"checked": 0, "listed": 0, "alerted": 0}

    settings = get_settings()
    threshold = max(1, int(settings.dnsbl_stability_threshold or 2))

    for ip, role in targets:
        prev = _last_check_for(db, domain.id, ip)
        hits = check_ip(ip)
        sev = severity_for(hits)
        rec = BlacklistCheck(
            tenant_id=domain.tenant_id,
            domain_id=domain.id,
            ip=ip,
            role=role,
            listed_count=len(hits),
            severity=sev,
            summary=bl_summary(hits)[:480],
            hits_json=json.dumps(hits) if hits else None,
        )
        db.add(rec)
        counts["checked"] += 1
        prev_sev = prev.severity if prev else 0

        # Stability-Threshold: only emit a state-change event when we have N
        # consecutive observations agreeing. This eliminates one-off rate-limit
        # NXDOMAIN flapping (the main source of alert-loops).
        stable_listed = (sev >= 2)
        stable_clean = (sev == 0)
        if threshold > 1:
            recent_records = db.execute(
                select(BlacklistCheck)
                .where(BlacklistCheck.domain_id == domain.id, BlacklistCheck.ip == ip)
                .order_by(desc(BlacklistCheck.checked_at))
                .limit(threshold - 1)
            ).scalars().all()
            # Combine current + last (threshold-1) checks
            last_severities = [sev] + [r.severity for r in recent_records]
            stable_listed = stable_listed and all(s >= 2 for s in last_severities)
            stable_clean = stable_clean and all(s == 0 for s in last_severities)

        # Decide whether to alert — but suppress if we already did so within cooldown.
        event_type: str | None = None
        if hits:
            counts["listed"] += 1
            if stable_listed and sev > prev_sev and tenant:
                event_type = "blacklist_alerts"
        else:
            if stable_clean and prev and prev_sev >= 2 and tenant:
                event_type = "blacklist_resolved"

        if event_type and tenant:
            recent = _recently_alerted(db, domain.id, ip, event_type)
            if recent:
                age_hours = (datetime.now(timezone.utc) - recent.alerted_at).total_seconds() / 3600.0
                log.info("Blacklist %s for %s/%s suppressed (last sent %.1fh ago, cooldown %dh)",
                         event_type, domain.name, ip, age_hours, ALERT_COOLDOWN_HOURS)
            else:
                _send_alert(tenant, domain, ip, role, hits, db, event_type=event_type)
                rec.alerted_event = event_type
                rec.alerted_at = datetime.now(timezone.utc)
                counts["alerted"] += 1

    db.commit()
    return counts


def run_all_blacklist_checks() -> dict:
    """Scheduled-job entrypoint. Iterate over all verified domains."""
    totals = {"domains": 0, "checked": 0, "listed": 0, "alerted": 0}
    with SessionLocal() as db:
        domains = db.execute(select(Domain)).scalars().all()
        for d in domains:
            try:
                stats = check_domain(db, d)
                totals["domains"] += 1
                totals["checked"] += stats["checked"]
                totals["listed"] += stats["listed"]
                totals["alerted"] += stats["alerted"]
            except Exception as e:  # noqa: BLE001
                log.exception("Blacklist check failed for %s: %s", d.name, e)
    log.info("Blacklist run complete: %s", totals)
    return totals
