from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..models import User
from ..rate_limit import login_limiter
from ..security import verify_password
from ..templating import render

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "login.html", error=None, allow_signup=get_settings().allow_signup)


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "anon"
    if not login_limiter.take(f"login:{ip}"):
        return render(request, "login.html",
                      error="Zu viele Versuche. Bitte einen Moment warten.",
                      allow_signup=get_settings().allow_signup)
    user = db.execute(select(User).where(User.email == email.lower().strip())).scalars().first()
    if not user or not verify_password(password, user.password_hash):
        audit.record(db, action="auth.login.failed", target_type="user",
                     target_id=email.lower().strip(), ip=ip, commit=True)
        return render(request, "login.html", error="Falsche E-Mail oder Passwort.",
                      allow_signup=get_settings().allow_signup)
    request.session.clear()
    request.session["user_id"] = user.id
    audit.record(db, user=user, action="auth.login", ip=ip, commit=True)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("user_id")
    if uid:
        u = db.get(User, uid)
        if u:
            audit.record(db, user=u, action="auth.logout",
                         ip=request.client.host if request.client else None, commit=True)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
