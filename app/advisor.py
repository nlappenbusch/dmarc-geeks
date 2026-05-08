"""DMARC policy advisor — recommend p= moves based on observed pass rate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Domain, IpAllowlist, Record, Report
from .stats import sender_label


@dataclass
class Advice:
    level: str  # ok, info, warn, danger
    headline: str
    body: str
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None


def _aligned(dkim: Optional[str], spf: Optional[str]) -> bool:
    return dkim == "pass" or spf == "pass"


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate(db: Session, domain: Domain) -> list[Advice]:
    out: list[Advice] = []
    since30 = datetime.now(timezone.utc) - timedelta(days=30)

    rows = db.execute(
        select(Record.dkim_eval, Record.spf_eval, Record.disposition,
               func.coalesce(func.sum(Record.count), 0))
        .join(Report, Report.id == Record.report_id)
        .where(Report.domain_id == domain.id, Report.date_begin >= since30)
        .group_by(Record.dkim_eval, Record.spf_eval, Record.disposition)
    ).all()

    total = sum(int(c) for *_, c in rows)
    aligned = sum(int(c) for d, s, _, c in rows if _aligned(d, s))
    pass_rate = (100.0 * aligned / total) if total else 0.0

    last = db.execute(
        select(Report.policy_p, Report.date_end)
        .where(Report.domain_id == domain.id)
        .order_by(Report.date_end.desc()).limit(1)
    ).first()

    current_p = (last[0] if last else None) or "none"
    last_seen = _to_utc(last[1] if last else None)

    # No data
    if total == 0:
        out.append(Advice(
            level="info",
            headline="Noch keine Daten",
            body="Reports trudeln meist 24 h nach DNS-Setup ein. ISPs senden 1× pro Tag.",
            cta_text="DNS-Setup prüfen", cta_url=f"/help#domain-rua",
        ))
        return out

    # Stale data
    if last_seen and (datetime.now(timezone.utc) - last_seen).days > 5:
        out.append(Advice(
            level="warn",
            headline=f"Letzter Report vor {(datetime.now(timezone.utc) - last_seen).days} Tagen",
            body="Eingehende Reports versiegt? Mailbox-Polling und DMARC-Record prüfen.",
            cta_text="Mailbox prüfen", cta_url="/mailboxes",
        ))

    # Pass-rate-based advice
    if total >= 100:
        if pass_rate >= 99 and current_p == "none":
            out.append(Advice(
                level="ok",
                headline=f"Bereit für p=quarantine ({pass_rate:.1f} % pass)",
                body="Stabile Pass-Rate über 30 Tage. Du kannst die Policy schärfen, "
                     "um Spoofing aktiv zu blockieren.",
                cta_text="Wie schärfen?", cta_url="/help#domain-rua",
            ))
        elif pass_rate >= 99 and current_p == "quarantine":
            out.append(Advice(
                level="ok",
                headline=f"Bereit für p=reject ({pass_rate:.1f} % pass)",
                body="Quarantine läuft sauber. Empfohlener nächster Schritt: p=reject.",
                cta_text="Wie schärfen?", cta_url="/help#domain-rua",
            ))
        elif pass_rate < 90:
            out.append(Advice(
                level="warn",
                headline=f"Niedrige Pass-Rate ({pass_rate:.1f} %)",
                body="Bevor du die Policy schärfst: legitime Quellen identifizieren und "
                     "in SPF/DKIM aufnehmen. Top-Quellen unten prüfen.",
            ))
        elif pass_rate < 99 and current_p in (None, "none"):
            out.append(Advice(
                level="info",
                headline=f"Noch nicht ganz reif ({pass_rate:.1f} % pass)",
                body="Pass-Rate sollte vor dem Schärfen über 99 % liegen. "
                     "Fail-Quellen identifizieren — meist 1-2 fehlkonfigurierte Dienste.",
            ))
    else:
        out.append(Advice(
            level="info",
            headline="Noch zu wenig Daten",
            body=f"Erst {total} Nachrichten in 30 Tagen. Belastbare Empfehlung ab ~100.",
        ))

    # New-source detection: IPs that first appeared in the last 3 days
    cutoff_new = datetime.now(timezone.utc) - timedelta(days=3)
    first_seen = db.execute(
        select(Record.source_ip, Record.source_host, func.min(Report.date_begin),
               func.coalesce(func.sum(Record.count), 0))
        .join(Report, Report.id == Record.report_id)
        .where(Report.domain_id == domain.id)
        .group_by(Record.source_ip, Record.source_host)
        .having(func.min(Report.date_begin) >= cutoff_new)
        .order_by(func.coalesce(func.sum(Record.count), 0).desc())
        .limit(3)
    ).all()
    allow_set = set(db.execute(
        select(IpAllowlist.ip_or_cidr).where(IpAllowlist.domain_id == domain.id)
    ).scalars().all())
    for ip, host, first_seen_at, vol in first_seen:
        if ip in allow_set or int(vol) < 5:
            continue
        days_ago = (datetime.now(timezone.utc) - _to_utc(first_seen_at)).days if first_seen_at else 0
        label = sender_label(host, ip)
        # Known service vs unknown
        if label not in ("Unbekannt", f"IP {ip}") and not label.startswith("IP "):
            out.append(Advice(
                level="info",
                headline=f"Neuer Sender erkannt: {label}",
                body=(f"{ip} ({label}) sendet seit {days_ago} Tag(en) — "
                      f"{int(vol)} Nachrichten. In Allowlist aufnehmen?"),
                cta_text="Zur Allowlist", cta_url=f"/domains/{domain.id}#allowlist",
            ))
        else:
            out.append(Advice(
                level="warn",
                headline="Unbekannte Quelle entdeckt",
                body=(f"{ip}{' (' + host + ')' if host else ''} sendet seit "
                      f"{days_ago} Tag(en) — {int(vol)} Nachrichten. "
                      "Wenn legitim: in Allowlist; sonst beobachten."),
                cta_text="IP-Detail ansehen", cta_url=f"/sources/{ip}",
            ))

    # Spike detection (last 7d vs prior 7-30d)
    since7 = datetime.now(timezone.utc) - timedelta(days=7)
    rec_rows = db.execute(
        select(Record.dkim_eval, Record.spf_eval, func.coalesce(func.sum(Record.count), 0))
        .join(Report, Report.id == Record.report_id)
        .where(Report.domain_id == domain.id, Report.date_begin >= since7)
        .group_by(Record.dkim_eval, Record.spf_eval)
    ).all()
    rec_total = sum(int(c) for *_, c in rec_rows) or 0
    rec_aligned = sum(int(c) for d, s, c in rec_rows if _aligned(d, s))
    rec_rate = (100.0 * rec_aligned / rec_total) if rec_total else 0.0
    if rec_total >= 50 and pass_rate - rec_rate >= 10:
        out.append(Advice(
            level="warn",
            headline=f"Pass-Rate fällt — letzte 7 Tage nur {rec_rate:.1f} %",
            body=f"30-Tage-Schnitt: {pass_rate:.1f} %. Eine Quelle könnte gerade gebrochen sein "
                 "(neuer Mailing-Dienst, abgelaufener DKIM-Selector, …). Top-Quellen prüfen.",
        ))

    return out
