"""Audit log helper."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from .models import AuditEvent, User

log = logging.getLogger(__name__)


def record(
    db: Session,
    *,
    action: str,
    user: Optional[User] = None,
    tenant_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    details: Optional[dict] = None,
    ip: Optional[str] = None,
    commit: bool = False,
) -> AuditEvent:
    ev = AuditEvent(
        tenant_id=tenant_id if tenant_id is not None else (user.tenant_id if user else None),
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=json.dumps(details, default=str) if details else None,
        ip=ip,
    )
    db.add(ev)
    if commit:
        db.commit()
    return ev
