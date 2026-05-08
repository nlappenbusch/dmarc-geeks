from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin
from ..models import ApiKey, User
from ..security import hash_password, make_token
from ..templating import render

router = APIRouter(prefix="/api-keys")


def _get(db: Session, key_id: int, tid: int) -> ApiKey:
    k = db.get(ApiKey, key_id)
    if not k or k.tenant_id != tid:
        raise HTTPException(status_code=404, detail="API-Key not found")
    return k


@router.get("")
def list_keys(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    keys = db.execute(
        select(ApiKey).where(ApiKey.tenant_id == effective_tenant_id(request, user)).order_by(ApiKey.created_at.desc())
    ).scalars().all()
    new_secret = request.session.pop("new_api_key", None)
    return render(request, "api_keys.html", user=user, tenant=effective_tenant(request, user, db), keys=keys,
                  new_secret=new_secret, active="api-keys")


@router.post("")
def create_key(
    request: Request,
    label: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    label = label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label fehlt")
    prefix = "dmk_" + make_token(6)[:8]
    secret = make_token(32)
    full = f"{prefix}.{secret}"
    k = ApiKey(
        tenant_id=effective_tenant_id(request, user),
        label=label,
        prefix=prefix,
        secret_hash=hash_password(secret),
        created_by_user_id=user.id,
    )
    db.add(k)
    audit.record(db, user=user, action="api_key.create", target_type="api_key", target_id=prefix,
                 details={"label": label}, ip=request.client.host if request.client else None)
    db.commit()
    request.session["new_api_key"] = full
    return RedirectResponse("/api-keys", status_code=303)


@router.post("/{key_id}/revoke")
def revoke_key(key_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    k = _get(db, key_id, effective_tenant_id(request, user))
    if k.revoked_at is None:
        k.revoked_at = datetime.now(timezone.utc)
        audit.record(db, user=user, action="api_key.revoke", target_type="api_key",
                     target_id=k.prefix, ip=request.client.host if request.client else None)
        db.commit()
    return RedirectResponse("/api-keys", status_code=303)


@router.post("/{key_id}/delete")
def delete_key(key_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    k = _get(db, key_id, effective_tenant_id(request, user))
    audit.record(db, user=user, action="api_key.delete", target_type="api_key",
                 target_id=k.prefix, ip=request.client.host if request.client else None)
    db.delete(k)
    db.commit()
    return RedirectResponse("/api-keys", status_code=303)
