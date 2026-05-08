from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin
from ..mail import smtp_configured
from ..models import CustomerProfile, TenantSettings, User
from ..templating import render

router = APIRouter(prefix="/settings")


def _ensure(db: Session, tenant_id: int) -> TenantSettings:
    s = db.get(TenantSettings, tenant_id)
    if s is None:
        s = TenantSettings(tenant_id=tenant_id)
        db.add(s)
        db.flush()
    return s


def _ensure_profile(db: Session, tenant_id: int) -> CustomerProfile:
    p = db.get(CustomerProfile, tenant_id)
    if p is None:
        p = CustomerProfile(tenant_id=tenant_id)
        db.add(p)
        db.flush()
    return p


@router.get("")
def view_settings(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = _ensure(db, effective_tenant_id(request, user))
    profile = _ensure_profile(db, effective_tenant_id(request, user))
    return render(request, "settings.html", user=user, tenant=effective_tenant(request, user, db), settings=s,
                  profile=profile, smtp_ready=smtp_configured(), active="settings")


@router.post("/brand")
def save_brand(
    request: Request,
    brand_color: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    s = _ensure(db, effective_tenant_id(request, user))
    s.brand_color = brand_color.strip() or "#2563eb"
    audit.record(db, user=user, action="settings.brand", target_type="tenant",
                 target_id=effective_tenant_id(request, user), details={"brand_color": s.brand_color},
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok", "text": "Markenfarbe gespeichert."}
    return RedirectResponse("/settings", status_code=303)


@router.post("/profile")
def save_profile(
    request: Request,
    company_name: str = Form(""),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
    street: str = Form(""),
    postal_code: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    vat_id: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone
    p = _ensure_profile(db, effective_tenant_id(request, user))
    p.company_name = company_name.strip() or None
    p.contact_name = contact_name.strip() or None
    p.contact_email = contact_email.strip() or None
    p.contact_phone = contact_phone.strip() or None
    p.street = street.strip() or None
    p.postal_code = postal_code.strip() or None
    p.city = city.strip() or None
    p.country = country.strip() or None
    p.vat_id = vat_id.strip() or None
    p.notes = notes.strip() or None
    p.updated_at = datetime.now(timezone.utc)
    audit.record(db, user=user, action="settings.profile", target_type="tenant",
                 target_id=effective_tenant_id(request, user),
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok", "text": "Kundendaten gespeichert."}
    return RedirectResponse("/settings", status_code=303)


@router.post("/notifications")
def save_notifications(
    request: Request,
    weekly_digest_enabled: bool = Form(False),
    digest_recipients: str = Form(""),
    spike_alert_enabled: bool = Form(False),
    spike_threshold_pct: int = Form(10),
    spike_min_volume: int = Form(100),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    s = _ensure(db, effective_tenant_id(request, user))
    s.weekly_digest_enabled = weekly_digest_enabled
    s.digest_recipients = digest_recipients.strip() or None
    s.spike_alert_enabled = spike_alert_enabled
    s.spike_threshold_pct = max(1, min(100, spike_threshold_pct))
    s.spike_min_volume = max(1, spike_min_volume)
    audit.record(db, user=user, action="settings.notifications", target_type="tenant",
                 target_id=effective_tenant_id(request, user),
                 ip=request.client.host if request.client else None)
    db.commit()
    request.session["flash"] = {"kind": "ok", "text": "Benachrichtigungen gespeichert."}
    return RedirectResponse("/settings", status_code=303)
