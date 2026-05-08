"""Reseller-Admin-Bereich. Sichtbar für User mit is_reseller_admin oder is_superadmin.

A Reseller is the MSP layer above tenants. The MSP-Admin manages multiple
customer tenants under their own reseller, with shared branding (logo, colour,
app name). They can enter any of their customer tenants like a superadmin.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..dependencies import require_reseller_admin
from ..imap_poller import is_polling, poll_in_background
from ..models import CustomerProfile, Domain, Mailbox, Report, Reseller, Tenant, TenantSettings, User
from ..security import encrypt_secret, hash_password
from ..stats import reseller_overview
from ..templating import render

router = APIRouter(prefix="/reseller")

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(s: str) -> str:
    out = _SLUG_RE.sub("-", s.lower()).strip("-")
    return out or "tenant"


def _user_reseller(db: Session, user: User) -> Reseller | None:
    """The reseller this user manages. Superadmin manages the platform-reseller's customers
    by default; a reseller-admin manages their own tenant's reseller."""
    if user.is_superadmin and not user.is_reseller_admin:
        # Superadmin sees ALL resellers via /admin/, but on /reseller defaults to platform
        return db.execute(select(Reseller).where(Reseller.is_platform.is_(True))).scalars().first()
    tenant = db.get(Tenant, user.tenant_id)
    if tenant and tenant.reseller_id:
        return db.get(Reseller, tenant.reseller_id)
    return None


@router.get("")
def reseller_dashboard(request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    if not reseller:
        raise HTTPException(status_code=404, detail="Kein Reseller-Profil")
    overview = reseller_overview(db, reseller_id=reseller.id, days=30)
    return render(request, "reseller_dashboard.html", user=user, tenant=user.tenant,
                  reseller=reseller, overview=overview, active="reseller")


@router.post("/tenants")
def create_customer_tenant(
    request: Request,
    name: str = Form(...),
    admin_email: str = Form(...),
    admin_password: str = Form(...),
    company_name: str = Form(""),
    user: User = Depends(require_reseller_admin),
    db: Session = Depends(get_db),
):
    reseller = _user_reseller(db, user)
    if not reseller:
        raise HTTPException(status_code=404, detail="Kein Reseller-Profil")
    name = name.strip()
    admin_email = admin_email.lower().strip()
    if not name or not admin_email or len(admin_password) < 8:
        raise HTTPException(status_code=400, detail="Eingaben unvollständig")
    # Seat limit
    used = db.execute(select(func.count(Tenant.id)).where(Tenant.reseller_id == reseller.id)).scalar() or 0
    if used >= reseller.seat_limit:
        request.session["flash"] = {"kind": "error",
            "text": f"Seat-Limit erreicht ({reseller.seat_limit}). Plan upgraden."}
        return RedirectResponse("/reseller", status_code=303)
    if db.execute(select(User).where(User.email == admin_email)).scalars().first():
        request.session["flash"] = {"kind": "error", "text": "E-Mail existiert bereits."}
        return RedirectResponse("/reseller", status_code=303)
    base = _slugify(name); slug = base; n = 1
    while db.execute(select(Tenant).where(Tenant.slug == slug)).scalars().first():
        n += 1; slug = f"{base}-{n}"
    t = Tenant(name=name, slug=slug, reseller_id=reseller.id)
    db.add(t); db.flush()
    if db.get(TenantSettings, t.id) is None:
        db.add(TenantSettings(tenant_id=t.id))
    if db.get(CustomerProfile, t.id) is None:
        db.add(CustomerProfile(tenant_id=t.id, company_name=company_name.strip() or name,
                                contact_email=admin_email))
    admin = User(email=admin_email, password_hash=hash_password(admin_password),
                  tenant_id=t.id, is_admin=True)
    db.add(admin)
    audit.record(db, user=user, action="reseller.tenant.create", target_type="tenant",
                 target_id=t.id, details={"name": name, "admin_email": admin_email},
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok", "text": f"Endkunde „{name}\" angelegt."}
    return RedirectResponse("/reseller", status_code=303)


@router.post("/tenants/{tenant_id}/enter")
def enter_customer_tenant(tenant_id: int, request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    t = db.get(Tenant, tenant_id)
    if not t or (not user.is_superadmin and t.reseller_id != reseller.id):
        raise HTTPException(status_code=404, detail="Tenant nicht gefunden")
    request.session["acting_as_tenant_id"] = t.id
    audit.record(db, user=user, action="reseller.tenant.enter", target_type="tenant",
                 target_id=t.id, ip=request.client.host if request.client else None, commit=True)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/tenants/{tenant_id}/delete")
def delete_customer_tenant(tenant_id: int, request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    t = db.get(Tenant, tenant_id)
    if not t or (not user.is_superadmin and t.reseller_id != reseller.id):
        raise HTTPException(status_code=404, detail="Tenant nicht gefunden")
    if t.id == user.tenant_id:
        raise HTTPException(status_code=400, detail="Eigenen Tenant nicht löschen")
    audit.record(db, user=user, action="reseller.tenant.delete", target_type="tenant",
                 target_id=t.id, ip=request.client.host if request.client else None)
    db.delete(t)
    db.commit()
    return RedirectResponse("/reseller", status_code=303)


@router.get("/mailboxes")
def list_reseller_mailboxes(request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    if not reseller:
        raise HTTPException(status_code=404, detail="Kein Reseller-Profil")
    mailboxes = db.execute(
        select(Mailbox).where(Mailbox.reseller_id == reseller.id).order_by(Mailbox.label)
    ).scalars().all()
    polling_ids = {m.id for m in mailboxes if is_polling(m.id)}
    return render(request, "reseller_mailboxes.html", user=user, tenant=user.tenant,
                  reseller=reseller, mailboxes=mailboxes, polling_ids=polling_ids,
                  active="reseller")


@router.post("/mailboxes")
def create_reseller_mailbox(
    request: Request,
    label: str = Form(...),
    host: str = Form(...),
    port: int = Form(993),
    use_ssl: bool = Form(False),
    username: str = Form(...),
    password: str = Form(...),
    folder: str = Form("INBOX"),
    move_to_folder: str = Form(""),
    enabled: bool = Form(False),
    user: User = Depends(require_reseller_admin),
    db: Session = Depends(get_db),
):
    reseller = _user_reseller(db, user)
    if not reseller:
        raise HTTPException(status_code=404, detail="Kein Reseller-Profil")
    mb = Mailbox(
        reseller_id=reseller.id, tenant_id=None,
        label=label.strip(), host=host.strip(), port=port, use_ssl=use_ssl,
        username=username.strip(), password_encrypted=encrypt_secret(password),
        folder=folder.strip() or "INBOX",
        move_to_folder=(move_to_folder.strip() or None),
        enabled=enabled,
    )
    db.add(mb)
    audit.record(db, user=user, action="reseller.mailbox.create", target_type="mailbox",
                 target_id=label, details={"host": host, "username": username},
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok",
        "text": f"Reseller-Mailbox „{label}\" angelegt. Reports werden automatisch nach Domain auf die richtigen Endkunden geroutet."}
    return RedirectResponse("/reseller/mailboxes", status_code=303)


@router.post("/mailboxes/{mailbox_id}/poll")
def reseller_mailbox_poll(mailbox_id: int, request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    mb = db.get(Mailbox, mailbox_id)
    if not mb or mb.reseller_id != reseller.id:
        raise HTTPException(status_code=404, detail="Mailbox nicht gefunden")
    started = poll_in_background(mb.id)
    request.session["flash"] = {
        "kind": "ok" if started else "warn",
        "text": f"„{mb.label}\": " + ("Prüfung läuft im Hintergrund." if started else "läuft bereits."),
    }
    return RedirectResponse("/reseller/mailboxes", status_code=303)


@router.post("/mailboxes/{mailbox_id}/toggle")
def reseller_mailbox_toggle(mailbox_id: int, request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    mb = db.get(Mailbox, mailbox_id)
    if not mb or mb.reseller_id != reseller.id:
        raise HTTPException(status_code=404, detail="Mailbox nicht gefunden")
    mb.enabled = not mb.enabled
    db.commit()
    return RedirectResponse("/reseller/mailboxes", status_code=303)


@router.post("/mailboxes/{mailbox_id}/delete")
def reseller_mailbox_delete(mailbox_id: int, request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    mb = db.get(Mailbox, mailbox_id)
    if not mb or mb.reseller_id != reseller.id:
        raise HTTPException(status_code=404, detail="Mailbox nicht gefunden")
    audit.record(db, user=user, action="reseller.mailbox.delete", target_type="mailbox",
                 target_id=mb.label, ip=request.client.host if request.client else None)
    db.delete(mb)
    db.commit()
    return RedirectResponse("/reseller/mailboxes", status_code=303)


@router.get("/users")
def list_reseller_users(request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    if not reseller:
        raise HTTPException(status_code=404, detail="Kein Reseller-Profil")
    rows = db.execute(
        select(User, Tenant).join(Tenant, Tenant.id == User.tenant_id)
        .where(Tenant.reseller_id == reseller.id).order_by(Tenant.name, User.email)
    ).all()
    customer_tenants = db.execute(
        select(Tenant).where(Tenant.reseller_id == reseller.id).order_by(Tenant.name)
    ).scalars().all()
    return render(request, "reseller_users.html", user=user, tenant=user.tenant,
                  reseller=reseller, rows=rows, customer_tenants=customer_tenants,
                  active="reseller")


@router.post("/users")
def create_reseller_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    tenant_id: int = Form(...),
    is_admin: bool = Form(False),
    user: User = Depends(require_reseller_admin),
    db: Session = Depends(get_db),
):
    reseller = _user_reseller(db, user)
    target_tenant = db.get(Tenant, tenant_id)
    if not target_tenant or target_tenant.reseller_id != reseller.id:
        raise HTTPException(status_code=404, detail="Tenant gehört nicht zu deinem Reseller")
    email = email.lower().strip()
    if not email or len(password) < 8:
        request.session["flash"] = {"kind": "error", "text": "Passwort min. 8 Zeichen."}
        return RedirectResponse("/reseller/users", status_code=303)
    if db.execute(select(User).where(User.email == email)).scalars().first():
        request.session["flash"] = {"kind": "error", "text": "E-Mail existiert bereits."}
        return RedirectResponse("/reseller/users", status_code=303)
    new_user = User(email=email, password_hash=hash_password(password),
                    tenant_id=target_tenant.id, is_admin=is_admin)
    db.add(new_user)
    audit.record(db, user=user, action="reseller.user.create", target_type="user",
                 target_id=email, details={"tenant": target_tenant.slug, "is_admin": is_admin},
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok",
        "text": f"User {email} in Tenant „{target_tenant.name}\" angelegt."}
    return RedirectResponse("/reseller/users", status_code=303)


@router.post("/users/{user_id}/role")
def set_reseller_user_role(
    user_id: int,
    request: Request,
    role: str = Form(...),
    user: User = Depends(require_reseller_admin),
    db: Session = Depends(get_db),
):
    reseller = _user_reseller(db, user)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    target_tenant = db.get(Tenant, target.tenant_id)
    if not target_tenant or target_tenant.reseller_id != reseller.id:
        raise HTTPException(status_code=404, detail="User gehört nicht zu deinem Reseller")
    if target.is_superadmin and not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    if target.id == user.id:
        request.session["flash"] = {"kind": "error", "text": "Eigene Rolle kann nicht geändert werden."}
        return RedirectResponse("/reseller/users", status_code=303)
    if role == "admin":
        target.is_admin = True
    elif role == "member":
        target.is_admin = False
    else:
        raise HTTPException(status_code=400, detail="Ungültige Rolle")
    audit.record(db, user=user, action="reseller.user.role", target_type="user",
                 target_id=target.email, details={"new_role": role, "tenant": target_tenant.slug},
                 ip=request.client.host if request.client else None)
    db.commit()
    return RedirectResponse("/reseller/users", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_reseller_user(
    user_id: int,
    request: Request,
    user: User = Depends(require_reseller_admin),
    db: Session = Depends(get_db),
):
    reseller = _user_reseller(db, user)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    target_tenant = db.get(Tenant, target.tenant_id)
    if not target_tenant or target_tenant.reseller_id != reseller.id:
        raise HTTPException(status_code=404, detail="User gehört nicht zu deinem Reseller")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Kann sich nicht selbst löschen")
    if target.is_superadmin and not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    audit.record(db, user=user, action="reseller.user.delete", target_type="user",
                 target_id=target.email, ip=request.client.host if request.client else None)
    db.delete(target)
    db.commit()
    return RedirectResponse("/reseller/users", status_code=303)


@router.get("/branding")
def branding_view(request: Request, user: User = Depends(require_reseller_admin), db: Session = Depends(get_db)):
    reseller = _user_reseller(db, user)
    if not reseller:
        raise HTTPException(status_code=404, detail="Kein Reseller-Profil")
    return render(request, "reseller_branding.html", user=user, tenant=user.tenant,
                  reseller=reseller, active="reseller")


@router.post("/branding")
def branding_save(
    request: Request,
    app_name: str = Form(...),
    brand_color: str = Form(...),
    logo_url: str = Form(""),
    support_email: str = Form(""),
    custom_domain: str = Form(""),
    imprint_html: str = Form(""),
    privacy_html: str = Form(""),
    user: User = Depends(require_reseller_admin),
    db: Session = Depends(get_db),
):
    reseller = _user_reseller(db, user)
    if not reseller:
        raise HTTPException(status_code=404, detail="Kein Reseller-Profil")
    reseller.app_name = app_name.strip() or "DMARC Aggregator"
    reseller.brand_color = brand_color.strip() or "#2563eb"
    reseller.logo_url = logo_url.strip() or None
    reseller.support_email = support_email.strip() or None
    reseller.custom_domain = custom_domain.strip().lower() or None
    reseller.imprint_html = imprint_html.strip() or None
    reseller.privacy_html = privacy_html.strip() or None
    audit.record(db, user=user, action="reseller.branding.save", target_type="reseller",
                 target_id=reseller.id, ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok", "text": "Branding gespeichert."}
    return RedirectResponse("/reseller/branding", status_code=303)
