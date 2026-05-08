"""Tenant-wide notification dispatcher with per-user opt-out preferences.

A single `notify_tenant()` call fans out to all relevant users of a tenant,
respecting their NotificationPreference flags and a tenant-level digest
recipient override (when set).

Event types (keep stable — UI references these):
    blacklist_alerts        — IP newly listed on a DNSBL
    blacklist_resolved      — Previously listed IP is now clean
    dmarc_spike             — Sudden change in DMARC pass rate
    weekly_digest           — Weekly summary mail
    new_sender_detected     — Previously unseen sender IP
    domain_added            — A new domain was added (admin-info)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mail
from .models import NotificationPreference, Tenant, User

log = logging.getLogger(__name__)

EVENT_TYPES = [
    "blacklist_alerts",
    "blacklist_resolved",
    "dmarc_spike",
    "weekly_digest",
    "new_sender_detected",
    "domain_added",
]

# Events that admins receive even if non-admin users opt out by default.
ADMIN_ONLY_EVENTS = {"domain_added"}


def _user_wants_event(db: Session, user: User, event_type: str) -> bool:
    """Return True if `user` wants notifications for `event_type`."""
    pref = db.get(NotificationPreference, user.id)
    if pref is None:
        # No prefs row → use Model defaults
        defaults = {
            "blacklist_alerts": True,
            "blacklist_resolved": True,
            "dmarc_spike": True,
            "weekly_digest": True,
            "new_sender_detected": True,
            "domain_added": False,
        }
        return defaults.get(event_type, True)
    return bool(getattr(pref, event_type, True))


def _is_quiet_hour(db: Session, user: User) -> bool:
    pref = db.get(NotificationPreference, user.id)
    if not pref or pref.quiet_hours_start is None or pref.quiet_hours_end is None:
        return False
    h = datetime.now(timezone.utc).hour
    s, e = pref.quiet_hours_start, pref.quiet_hours_end
    if s == e:
        return False
    if s < e:
        return s <= h < e
    # wraps midnight (e.g. 22 -> 6)
    return h >= s or h < e


def recipients_for(db: Session, tenant_id: int, event_type: str,
                   *, admin_only: bool = False) -> list[User]:
    """Return Users in `tenant_id` who want `event_type`.

    `admin_only=True` restricts to admin/superadmin users regardless of prefs
    (rare — used for security-sensitive operational alerts only).
    """
    q = select(User).where(User.tenant_id == tenant_id)
    if admin_only or event_type in ADMIN_ONLY_EVENTS:
        q = q.where((User.is_admin.is_(True)) | (User.is_superadmin.is_(True)))
    users = db.execute(q).scalars().all()
    return [u for u in users if _user_wants_event(db, u, event_type)
            and not _is_quiet_hour(db, u)]


def notify_tenant(
    db: Session,
    tenant_id: int,
    event_type: str,
    subject: str,
    text: str,
    *,
    html: Optional[str] = None,
    admin_only: bool = False,
) -> int:
    """Send a notification mail to all eligible users of a tenant.

    Returns the count of recipients the mail was attempted-sent to. Logs but
    swallows individual SMTP errors so one bad address doesn't kill the rest.
    """
    if event_type not in EVENT_TYPES:
        log.warning("notify_tenant: unknown event_type %r", event_type)
    users = recipients_for(db, tenant_id, event_type, admin_only=admin_only)
    if not users:
        log.info("notify_tenant tenant=%s event=%s — no recipients", tenant_id, event_type)
        return 0
    sent = 0
    for u in users:
        try:
            ok = mail.send_mail(to=u.email, subject=subject, text=text, html=html)
            if ok:
                sent += 1
        except Exception as e:  # noqa: BLE001
            log.warning("notify_tenant: failed for %s: %s", u.email, e)
    log.info("notify_tenant tenant=%s event=%s -> %d/%d sent", tenant_id, event_type,
             sent, len(users))
    return sent


def get_preference(db: Session, user_id: int) -> NotificationPreference:
    """Get-or-create the preference row for a user (with all defaults)."""
    pref = db.get(NotificationPreference, user_id)
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        db.flush()
    return pref
