from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin
from ..models import Tag, User
from ..templating import render

router = APIRouter(prefix="/tags")


@router.get("")
def list_tags(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    tags = db.execute(
        select(Tag).where(Tag.tenant_id == effective_tenant_id(request, user)).order_by(Tag.name)
    ).scalars().all()
    return render(request, "tags.html", user=user, tenant=effective_tenant(request, user, db), tags=tags, active="settings")


@router.post("")
def create_tag(
    request: Request,
    name: str = Form(...),
    color: str = Form("#64748b"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name fehlt")
    existing = db.execute(
        select(Tag).where(Tag.tenant_id == effective_tenant_id(request, user), Tag.name == name)
    ).scalars().first()
    if not existing:
        db.add(Tag(tenant_id=effective_tenant_id(request, user), name=name, color=color))
        audit.record(db, user=user, action="tag.create", target_type="tag", target_id=name,
                     ip=request.client.host if request.client else None)
        db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/{tag_id}/delete")
def delete_tag(tag_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(Tag, tag_id)
    if not t or t.tenant_id != effective_tenant_id(request, user):
        raise HTTPException(status_code=404, detail="Tag not found")
    audit.record(db, user=user, action="tag.delete", target_type="tag", target_id=t.name,
                 ip=request.client.host if request.client else None)
    db.delete(t)
    db.commit()
    return RedirectResponse("/tags", status_code=303)
