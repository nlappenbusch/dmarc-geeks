from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin
from ..models import User, Webhook
from ..security import make_token
from ..templating import render
from ..webhooks import emit as emit_event

router = APIRouter(prefix="/webhooks")


def _get(db: Session, wh_id: int, tid: int) -> Webhook:
    wh = db.get(Webhook, wh_id)
    if not wh or wh.tenant_id != tid:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return wh


@router.get("")
def list_webhooks(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    hooks = db.execute(
        select(Webhook).where(Webhook.tenant_id == effective_tenant_id(request, user)).order_by(Webhook.created_at.desc())
    ).scalars().all()
    return render(request, "webhooks.html", user=user, tenant=effective_tenant(request, user, db), hooks=hooks, active="webhooks")


@router.post("")
def create_webhook(
    request: Request,
    label: str = Form(...),
    url: str = Form(...),
    events: str = Form("report.imported"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    label = label.strip(); url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="URL muss mit http(s):// beginnen")
    wh = Webhook(
        tenant_id=effective_tenant_id(request, user), label=label, url=url, events=events.strip() or "report.imported",
        secret=make_token(24),
    )
    db.add(wh)
    audit.record(db, user=user, action="webhook.create", target_type="webhook", target_id=label,
                 details={"url": url}, ip=request.client.host if request.client else None)
    db.commit()
    return RedirectResponse("/webhooks", status_code=303)


@router.post("/{wh_id}/toggle")
def toggle(wh_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    wh = _get(db, wh_id, effective_tenant_id(request, user))
    wh.enabled = not wh.enabled
    db.commit()
    return RedirectResponse("/webhooks", status_code=303)


@router.post("/{wh_id}/test")
def test(wh_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    wh = _get(db, wh_id, effective_tenant_id(request, user))
    emit_event(effective_tenant_id(request, user), "test.ping", {"webhook_id": wh.id, "label": wh.label})
    return RedirectResponse("/webhooks", status_code=303)


@router.post("/{wh_id}/delete")
def delete(wh_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    wh = _get(db, wh_id, effective_tenant_id(request, user))
    audit.record(db, user=user, action="webhook.delete", target_type="webhook", target_id=wh.label,
                 ip=request.client.host if request.client else None)
    db.delete(wh)
    db.commit()
    return RedirectResponse("/webhooks", status_code=303)
