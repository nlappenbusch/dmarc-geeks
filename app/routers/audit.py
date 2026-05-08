from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin
from ..models import AuditEvent, User
from ..templating import render

router = APIRouter()


@router.get("/audit")
def view_audit(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    events = db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == effective_tenant_id(request, user))
        .order_by(AuditEvent.created_at.desc()).limit(500)
    ).scalars().all()
    return render(request, "audit_log.html", user=user, tenant=effective_tenant(request, user, db),
                  events=events, active="settings")
