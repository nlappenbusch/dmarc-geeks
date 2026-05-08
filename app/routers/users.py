from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin, require_user
from ..models import User
from ..security import hash_password, verify_password
from ..templating import render

router = APIRouter(prefix="/users")


@router.get("")
def list_users(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.execute(
        select(User).where(User.tenant_id == effective_tenant_id(request, user)).order_by(User.email)
    ).scalars().all()
    return render(request, "users.html", user=user, tenant=effective_tenant(request, user, db), users=users, active="users")


@router.post("")
def create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    is_admin: bool = Form(False),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = email.lower().strip()
    if not email or len(password) < 8:
        raise HTTPException(status_code=400, detail="Ungültige Eingaben (Passwort min. 8 Zeichen)")
    existing = db.execute(select(User).where(User.email == email)).scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="E-Mail existiert bereits")
    new_user = User(
        email=email,
        password_hash=hash_password(password),
        tenant_id=effective_tenant_id(request, user),
        is_admin=is_admin,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/role")
def set_user_role(
    user_id: int,
    request: Request,
    role: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Toggle a user between member (is_admin=False) and admin (is_admin=True)."""
    target = db.get(User, user_id)
    if not target or target.tenant_id != effective_tenant_id(request, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == user.id:
        request.session["flash"] = {"kind": "error", "text": "Eigene Rolle kann nicht geändert werden."}
        return RedirectResponse("/users", status_code=303)
    if target.is_superadmin and not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    if role == "admin":
        target.is_admin = True
    elif role == "member":
        target.is_admin = False
    else:
        raise HTTPException(status_code=400, detail=f"Ungültige Rolle: {role}")
    audit.record(db, user=user, action="user.role", target_type="user",
                 target_id=target.email, details={"new_role": role},
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok",
        "text": f"{target.email} ist jetzt {('Admin' if target.is_admin else 'Member')}."}
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/delete")
def delete_user(
    user_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target or target.tenant_id != effective_tenant_id(request, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Kann sich nicht selbst löschen")
    if target.is_superadmin and not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    db.delete(target)
    db.commit()
    return RedirectResponse("/users", status_code=303)


@router.get("/me")
def me(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return render(request, "me.html", user=user, tenant=user.tenant, active="me", error=None, success=None)


@router.post("/me/password")
def change_my_password(
    request: Request,
    current: str = Form(...),
    new: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not verify_password(current, user.password_hash):
        return render(request, "me.html", user=user, tenant=user.tenant, active="me",
                      error="Aktuelles Passwort falsch.", success=None)
    if len(new) < 8:
        return render(request, "me.html", user=user, tenant=user.tenant, active="me",
                      error="Neues Passwort muss min. 8 Zeichen haben.", success=None)
    user.password_hash = hash_password(new)
    db.commit()
    return render(request, "me.html", user=user, tenant=user.tenant, active="me",
                  error=None, success="Passwort geändert.")


@router.get("/me/notifications")
def my_notifications(request: Request, user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    """Show + edit notification preferences for the current user."""
    from .. import notify
    pref = notify.get_preference(db, user.id)
    db.commit()
    return render(request, "me_notifications.html", user=user, tenant=user.tenant,
                  pref=pref, active="me", flash=request.session.pop("flash", None))


@router.post("/me/notifications")
async def save_my_notifications(request: Request, user: User = Depends(require_user),
                                db: Session = Depends(get_db)):
    """Save notification preferences for the current user."""
    from .. import notify
    form = await request.form()
    pref = notify.get_preference(db, user.id)
    bool_fields = ["blacklist_alerts", "blacklist_resolved", "dmarc_spike",
                   "weekly_digest", "new_sender_detected", "domain_added"]
    for f in bool_fields:
        setattr(pref, f, form.get(f) in ("on", "true", "1"))

    # Quiet hours
    def _hour_or_none(v):
        try:
            v = (v or "").strip()
            if v == "": return None
            h = int(v)
            return h if 0 <= h <= 23 else None
        except (ValueError, TypeError):
            return None
    pref.quiet_hours_start = _hour_or_none(form.get("quiet_hours_start"))
    pref.quiet_hours_end = _hour_or_none(form.get("quiet_hours_end"))
    from datetime import datetime, timezone
    pref.updated_at = datetime.now(timezone.utc)
    db.commit()
    request.session["flash"] = "Benachrichtigungs-Einstellungen gespeichert."
    return RedirectResponse("/users/me/notifications", status_code=303)
