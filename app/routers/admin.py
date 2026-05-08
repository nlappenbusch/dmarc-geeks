import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..dependencies import require_superadmin
from ..models import CustomerProfile, Domain, IngestLog, Report, Reseller, Tenant, TenantSettings, User
from ..security import hash_password
from ..templating import render

router = APIRouter(prefix="/admin")

_slug_re = re.compile(r"[^a-z0-9-]+")


def _slugify(value: str) -> str:
    s = _slug_re.sub("-", value.lower()).strip("-")
    return s or "tenant"


@router.get("/tenants")
def list_tenants(request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            Tenant,
            func.count(func.distinct(User.id)).label("users"),
            func.count(func.distinct(Domain.id)).label("domains"),
            func.count(func.distinct(Report.id)).label("reports"),
        )
        .outerjoin(User, User.tenant_id == Tenant.id)
        .outerjoin(Domain, Domain.tenant_id == Tenant.id)
        .outerjoin(Report, Report.tenant_id == Tenant.id)
        .group_by(Tenant.id)
        .order_by(Tenant.name)
    ).all()
    return render(request, "admin_tenants.html", user=user, tenant=user.tenant,
                  rows=rows, active="admin")


@router.post("/tenants")
def create_tenant(
    name: str = Form(...),
    admin_email: str = Form(...),
    admin_password: str = Form(...),
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    name = name.strip()
    admin_email = admin_email.strip().lower()
    if not name or not admin_email or len(admin_password) < 8:
        raise HTTPException(status_code=400, detail="Eingaben unvollständig")
    base = _slugify(name)
    slug = base
    n = 1
    while db.execute(select(Tenant).where(Tenant.slug == slug)).scalars().first():
        n += 1
        slug = f"{base}-{n}"
    existing = db.execute(select(User).where(User.email == admin_email)).scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="E-Mail existiert bereits")
    t = Tenant(name=name, slug=slug)
    db.add(t)
    db.flush()
    if db.get(TenantSettings, t.id) is None:
        db.add(TenantSettings(tenant_id=t.id))
    if db.get(CustomerProfile, t.id) is None:
        db.add(CustomerProfile(tenant_id=t.id, company_name=name, contact_email=admin_email))
    admin = User(
        email=admin_email,
        password_hash=hash_password(admin_password),
        tenant_id=t.id,
        is_admin=True,
    )
    db.add(admin)
    db.commit()
    return RedirectResponse("/admin/tenants", status_code=303)


@router.post("/tenants/{tenant_id}/delete")
def delete_tenant(tenant_id: int, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if t.id == user.tenant_id:
        raise HTTPException(status_code=400, detail="Kann eigenen Tenant nicht löschen")
    db.delete(t)
    db.commit()
    return RedirectResponse("/admin/tenants", status_code=303)


@router.post("/tenants/{tenant_id}/enter")
def enter_tenant(tenant_id: int, request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    request.session["acting_as_tenant_id"] = t.id
    request.session["flash"] = {
        "kind": "warn",
        "text": f"Du betrittst Tenant {t.name}. Alle Ansichten zeigen jetzt deren Daten.",
    }
    from .. import audit as audit_mod
    audit_mod.record(db, user=user, action="tenant.enter", target_type="tenant",
                     target_id=t.id, ip=request.client.host if request.client else None,
                     commit=True)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/tenants/exit")
def exit_tenant(request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    if request.session.get("acting_as_tenant_id"):
        from .. import audit as audit_mod
        audit_mod.record(db, user=user, action="tenant.exit",
                         target_id=request.session.get("acting_as_tenant_id"),
                         ip=request.client.host if request.client else None, commit=True)
    request.session.pop("acting_as_tenant_id", None)
    return RedirectResponse("/admin/tenants", status_code=303)


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: int, request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    t = db.execute(
        select(Tenant).options(selectinload(Tenant.settings),
                                 selectinload(Tenant.users),
                                 selectinload(Tenant.domains)).where(Tenant.id == tenant_id)
    ).scalars().first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    profile = db.get(CustomerProfile, t.id)
    if profile is None:
        profile = CustomerProfile(tenant_id=t.id)
        db.add(profile); db.commit()
    n_reports = db.execute(
        select(func.count(Report.id)).where(Report.tenant_id == t.id)
    ).scalar() or 0
    return render(request, "admin_tenant_detail.html", user=user, tenant=user.tenant,
                  target=t, profile=profile, n_reports=n_reports, active="admin")


# --- Resellers ----------------------------------------------------------------
@router.get("/resellers")
def list_resellers(request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            Reseller,
            func.count(func.distinct(Tenant.id)).label("n_tenants"),
            func.count(func.distinct(Domain.id)).label("n_domains"),
            func.count(func.distinct(Report.id)).label("n_reports"),
        )
        .outerjoin(Tenant, Tenant.reseller_id == Reseller.id)
        .outerjoin(Domain, Domain.tenant_id == Tenant.id)
        .outerjoin(Report, Report.tenant_id == Tenant.id)
        .group_by(Reseller.id)
        .order_by(Reseller.is_platform.desc(), Reseller.name)
    ).all()
    return render(request, "admin_resellers.html", user=user, tenant=user.tenant,
                  rows=rows, active="admin")


@router.post("/resellers")
def create_reseller(
    name: str = Form(...),
    plan: str = Form("agency"),
    seat_limit: int = Form(25),
    request: Request = None,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name fehlt")
    base = _slugify(name); slug = base; n = 1
    while db.execute(select(Reseller).where(Reseller.slug == slug)).scalars().first():
        n += 1; slug = f"{base}-{n}"
    r = Reseller(name=name, slug=slug, is_platform=False, plan=plan,
                  seat_limit=max(1, seat_limit), app_name=name, brand_color="#2563eb")
    db.add(r)
    audit.record(db, user=user, action="reseller.create", target_type="reseller",
                 target_id=slug, details={"name": name, "plan": plan},
                 ip=request.client.host if request and request.client else None)
    db.commit()
    return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)


@router.get("/resellers/{reseller_id}")
def reseller_detail(reseller_id: int, request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    r = db.get(Reseller, reseller_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reseller not found")
    customer_tenants = db.execute(
        select(Tenant).where(Tenant.reseller_id == r.id).order_by(Tenant.name)
    ).scalars().all()
    reseller_admins = db.execute(
        select(User).join(Tenant, Tenant.id == User.tenant_id)
        .where(Tenant.reseller_id == r.id, User.is_reseller_admin.is_(True))
        .order_by(User.email)
    ).scalars().all()
    n_reports = db.execute(
        select(func.count(Report.id)).join(Tenant, Tenant.id == Report.tenant_id)
        .where(Tenant.reseller_id == r.id)
    ).scalar() or 0
    return render(request, "admin_reseller_detail.html", user=user, tenant=user.tenant,
                  target=r, customer_tenants=customer_tenants, reseller_admins=reseller_admins,
                  n_reports=n_reports, active="admin")


@router.post("/resellers/{reseller_id}")
def save_reseller(
    reseller_id: int,
    name: str = Form(...),
    app_name: str = Form(...),
    brand_color: str = Form("#2563eb"),
    logo_url: str = Form(""),
    support_email: str = Form(""),
    custom_domain: str = Form(""),
    plan: str = Form("agency"),
    seat_limit: int = Form(25),
    revenue_share_pct: int = Form(0),
    notes: str = Form(""),
    request: Request = None,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    r = db.get(Reseller, reseller_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reseller not found")
    r.name = name.strip() or r.name
    r.app_name = app_name.strip() or "DMARC Aggregator"
    r.brand_color = brand_color.strip() or "#2563eb"
    r.logo_url = logo_url.strip() or None
    r.support_email = support_email.strip() or None
    r.custom_domain = (custom_domain.strip().lower() or None)
    r.plan = plan
    r.seat_limit = max(1, seat_limit)
    r.revenue_share_pct = max(0, min(100, revenue_share_pct))
    r.notes = notes.strip() or None
    audit.record(db, user=user, action="reseller.update", target_type="reseller",
                 target_id=r.slug, ip=request.client.host if request and request.client else None)
    db.commit()
    if request:
        request.session["flash"] = {"kind": "ok", "text": f"Reseller „{r.name}\" gespeichert."}
    return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)


@router.post("/resellers/{reseller_id}/delete")
def delete_reseller(reseller_id: int, request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    r = db.get(Reseller, reseller_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reseller not found")
    if r.is_platform:
        raise HTTPException(status_code=400, detail="Plattform-Reseller kann nicht gelöscht werden")
    n_tenants = db.execute(select(func.count(Tenant.id)).where(Tenant.reseller_id == r.id)).scalar() or 0
    if n_tenants > 0:
        request.session["flash"] = {"kind": "error",
            "text": f"Reseller hat noch {n_tenants} Endkunden — erst dort löschen oder umziehen."}
        return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)
    audit.record(db, user=user, action="reseller.delete", target_type="reseller",
                 target_id=r.slug, ip=request.client.host if request.client else None)
    db.delete(r)
    db.commit()
    return RedirectResponse("/admin/resellers", status_code=303)


@router.post("/resellers/{reseller_id}/create-admin")
def create_reseller_admin(
    reseller_id: int,
    email: str = Form(...),
    password: str = Form(...),
    tenant_id: int = Form(0),
    request: Request = None,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Create a fresh user as Reseller-Admin for the given reseller.

    If `tenant_id` is 0 or unset, auto-creates an "Operations"-Tenant under the
    reseller. The reseller-admin lives in some tenant of the reseller (User
    needs tenant_id NOT NULL); operations-tenant is the cleanest pattern.
    """
    r = db.get(Reseller, reseller_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reseller not found")
    email = email.lower().strip()
    if not email or len(password) < 8:
        if request:
            request.session["flash"] = {"kind": "error", "text": "E-Mail oder Passwort ungültig (Passwort min. 8 Zeichen)."}
        return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)
    if db.execute(select(User).where(User.email == email)).scalars().first():
        if request:
            request.session["flash"] = {"kind": "error", "text": "E-Mail existiert bereits."}
        return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)

    # Resolve target tenant
    if tenant_id and tenant_id > 0:
        target_tenant = db.get(Tenant, tenant_id)
        if not target_tenant or target_tenant.reseller_id != r.id:
            if request:
                request.session["flash"] = {"kind": "error",
                    "text": "Tenant gehört nicht zu diesem Reseller."}
            return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)
    else:
        # Auto-create operations tenant
        ops_slug = f"{r.slug}-ops"
        n = 1
        while db.execute(select(Tenant).where(Tenant.slug == ops_slug)).scalars().first():
            n += 1; ops_slug = f"{r.slug}-ops-{n}"
        target_tenant = Tenant(
            reseller_id=r.id,
            name=f"{r.name} — Operations",
            slug=ops_slug,
        )
        db.add(target_tenant); db.flush()
        if db.get(TenantSettings, target_tenant.id) is None:
            db.add(TenantSettings(tenant_id=target_tenant.id))
        if db.get(CustomerProfile, target_tenant.id) is None:
            db.add(CustomerProfile(tenant_id=target_tenant.id,
                                     company_name=r.name, contact_email=email))

    new_user = User(
        email=email,
        password_hash=hash_password(password),
        tenant_id=target_tenant.id,
        is_admin=True,
        is_reseller_admin=True,
    )
    db.add(new_user)
    audit.record(db, user=user, action="reseller.admin.create", target_type="user",
                 target_id=email, details={"reseller": r.slug, "tenant": target_tenant.slug},
                 ip=request.client.host if request and request.client else None)
    db.commit()
    if request:
        request.session["flash"] = {"kind": "ok",
            "text": f"Reseller-Admin {email} im Tenant „{target_tenant.name}\" angelegt."}
    return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)


@router.post("/resellers/{reseller_id}/promote-admin")
def promote_reseller_admin(reseller_id: int, user_email: str = Form(...),
                            request: Request = None, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    r = db.get(Reseller, reseller_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reseller not found")
    target = db.execute(select(User).where(User.email == user_email.lower().strip())).scalars().first()
    if not target:
        if request:
            request.session["flash"] = {"kind": "error", "text": f"User {user_email} nicht gefunden."}
        return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)
    target_tenant = db.get(Tenant, target.tenant_id)
    if not target_tenant or target_tenant.reseller_id != r.id:
        if request:
            request.session["flash"] = {"kind": "error",
                "text": "User muss in einem Tenant dieses Resellers sein."}
        return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)
    target.is_reseller_admin = True
    audit.record(db, user=user, action="reseller.admin.promote", target_type="user",
                 target_id=target.email, details={"reseller": r.slug},
                 ip=request.client.host if request and request.client else None)
    db.commit()
    if request:
        request.session["flash"] = {"kind": "ok", "text": f"{target.email} ist jetzt Reseller-Admin."}
    return RedirectResponse(f"/admin/resellers/{r.id}", status_code=303)


@router.get("/ingest-log")
def ingest_log(request: Request, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(IngestLog).order_by(IngestLog.created_at.desc()).limit(200)
    ).scalars().all()
    return render(request, "admin_ingest_log.html", user=user, tenant=user.tenant,
                  rows=rows, active="admin")


# ========== SYSTEM / .env-Editor ==========

@router.get("/system")
def system_panel(request: Request, user: User = Depends(require_superadmin)):
    """Show .env editor + test buttons. Only superadmin."""
    from ..env_file import EDITABLE_FIELDS, read_env, is_sensitive, mask_value, _env_path
    from ..config import get_settings
    env = read_env()
    settings = get_settings()
    fields = []
    for f in EDITABLE_FIELDS:
        raw = env.get(f["key"], "")
        sensitive = is_sensitive(f["key"]) or f["kind"] in ("password", "secret")
        fields.append({**f,
            "value": raw,
            "display": mask_value(raw) if sensitive and raw else raw,
            "is_sensitive": sensitive,
            "is_set": bool(raw),
        })
    # Group by `group`
    groups: dict[str, list] = {}
    for f in fields:
        groups.setdefault(f["group"], []).append(f)

    return render(request, "admin_system.html", user=user, tenant=user.tenant,
                  groups=groups, env_path=str(_env_path()), settings=settings, active="admin-system")


@router.post("/system")
async def system_save(request: Request, user: User = Depends(require_superadmin),
                      db: Session = Depends(get_db)):
    """Save .env updates."""
    from ..env_file import EDITABLE_FIELDS, write_env, is_sensitive
    form = await request.form()
    updates: dict[str, str] = {}
    valid_keys = {f["key"] for f in EDITABLE_FIELDS}
    bool_keys = {f["key"] for f in EDITABLE_FIELDS if f["kind"] == "bool"}
    # Felder, die niemals leer geschrieben werden dürfen (sonst crashed die App).
    no_empty_keys = {"DATABASE_URL", "SECRET_KEY", "FERNET_KEY", "SUPERADMIN_EMAIL"}

    for k in valid_keys:
        if k in bool_keys:
            updates[k] = "true" if form.get(k) in ("on", "true", "1") else "false"
        else:
            v = form.get(k)
            if v is None:
                continue
            v = str(v).strip()
            # Sensitive Felder: leer = "alten Wert behalten" (in .env bleibt der bestehende Eintrag)
            if not v and is_sensitive(k):
                continue
            # Kritische Felder: leer ablehnen — sonst killt's den App-Start
            if not v and k in no_empty_keys:
                continue
            updates[k] = v

    result = write_env(updates)
    audit.record(db, action="system.env.save", user=user, target_type="env",
                 details={"changed": result["changed"]}, commit=True)

    # Drop the cached Settings so tests on this page see new values without
    # waiting for an app restart. Note: code paths that captured `get_settings()`
    # at import time (e.g. the DB engine) still need a real restart.
    from ..config import get_settings
    get_settings.cache_clear()
    # Also push updates into os.environ so a fresh Settings() can read them
    # even if .env file caching is in play.
    import os
    for k, v in updates.items():
        os.environ[k] = v

    request.session["flash"] = (f".env gespeichert · {len(result['changed'])} Änderungen. "
                                f"Tests rechts greifen sofort. App-Neustart nötig wenn DB/Secret/Fernet geändert wurde.")
    return RedirectResponse("/admin/system", status_code=303)


@router.post("/system/test/db")
def test_db(user: User = Depends(require_superadmin)):
    """Test DB connectivity."""
    from sqlalchemy import text
    from ..database import engine
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "msg": f"Verbindung zu Database erfolgreich · Dialect: {engine.dialect.name}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"Fehler: {e}"}


@router.post("/system/test/smtp")
async def test_smtp(request: Request, user: User = Depends(require_superadmin)):
    """Test SMTP by sending a probe mail to the superadmin.

    Negotiates capabilities (EHLO) before login: opportunistic STARTTLS if the
    server offers it, AUTH only if advertised. Falls back to anonymous submit
    when the server doesn't expose AUTH (common for internal relays on :25).
    """
    import smtplib
    from email.message import EmailMessage
    from ..config import get_settings
    s = get_settings()
    if not s.smtp_host:
        return {"ok": False, "msg": "SMTP_HOST ist nicht gesetzt."}
    form = await request.form()
    target = (form.get("to") or s.superadmin_email or user.email).strip()
    msg = EmailMessage()
    msg["Subject"] = "[DMARC Aggregator] SMTP-Test"
    msg["From"] = s.smtp_from or "dmarc-aggregator@localhost"
    msg["To"] = target
    msg.set_content(
        "Das ist eine Test-Mail vom DMARC-Aggregator-Admin-Panel.\n\n"
        "Wenn du das liest, funktioniert SMTP. Glückwunsch.\n\n"
        f"Host: {s.smtp_host}:{s.smtp_port} · STARTTLS={s.smtp_use_tls}\n"
    )

    import ssl as _ssl
    if s.smtp_tls_verify:
        tls_ctx = _ssl.create_default_context()
        verify_label = "Cert-Verify=on"
    else:
        tls_ctx = _ssl.create_default_context()
        tls_ctx.check_hostname = False
        tls_ctx.verify_mode = _ssl.CERT_NONE
        verify_label = "⚠️ Cert-Verify=OFF"

    info_log: list[str] = []
    try:
        if s.smtp_port == 465:
            srv = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=tls_ctx, timeout=20)
            srv.ehlo()
            info_log.append(f"SSL-Connect ({verify_label})")
        else:
            srv = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
            srv.ehlo()
            offers_starttls = srv.has_extn("starttls")
            if offers_starttls and (s.smtp_use_tls or s.smtp_port != 25):
                srv.starttls(context=tls_ctx)
                srv.ehlo()
                info_log.append(f"STARTTLS aktiv ({verify_label})")
            elif s.smtp_use_tls and not offers_starttls:
                info_log.append("STARTTLS gewünscht aber Server bietet's nicht")
            else:
                info_log.append("Klartext (kein STARTTLS)")

        # AUTH only if advertised AND user/pass set
        offers_auth = srv.has_extn("auth")
        if s.smtp_user and offers_auth:
            srv.login(s.smtp_user, s.smtp_password)
            info_log.append(f"AUTH als {s.smtp_user}")
        elif s.smtp_user and not offers_auth:
            info_log.append(f"AUTH nicht angeboten — sende anonym (User '{s.smtp_user}' ignoriert)")
        else:
            info_log.append("kein AUTH konfiguriert")

        srv.send_message(msg)
        srv.quit()
        return {"ok": True, "msg": f"Test-Mail an {target} verschickt · " + " · ".join(info_log) + ". Schau ins Postfach (auch Spam-Ordner)."}
    except smtplib.SMTPAuthenticationError as e:
        return {"ok": False, "msg": f"AUTH abgelehnt: {e.smtp_code} {e.smtp_error.decode(errors='replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}"}
    except smtplib.SMTPRecipientsRefused as e:
        return {"ok": False, "msg": f"Empfänger {target} abgelehnt: {e.recipients}"}
    except smtplib.SMTPSenderRefused as e:
        return {"ok": False, "msg": f"Absender {msg['From']} abgelehnt: {e.smtp_code} {e.smtp_error}"}
    except smtplib.SMTPException as e:
        return {"ok": False, "msg": f"SMTP-Fehler: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"Fehler: {e}"}


@router.post("/system/test/dns")
async def test_dns(request: Request, user: User = Depends(require_superadmin)):
    """Test DNS resolver against a target host."""
    from ..dns_utils import _resolver
    import dns.exception, dns.resolver
    form = await request.form()
    host = (form.get("host") or "google.com").strip().lower()
    if not host or "." not in host:
        return {"ok": False, "msg": "Bitte gültigen Hostname eingeben."}
    results = []
    for rtype in ("MX", "A", "TXT"):
        try:
            answers = _resolver.resolve(host, rtype, lifetime=3.0)
            count = sum(1 for _ in answers)
            results.append(f"{rtype}: {count}")
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            results.append(f"{rtype}: 0")
        except dns.exception.Timeout:
            return {"ok": False, "msg": f"DNS-Timeout für {host}"}
        except Exception as e:  # noqa: BLE001
            results.append(f"{rtype}: ERR ({e})")
    return {"ok": True, "msg": f"{host} aufgelöst · " + " · ".join(results)}


@router.post("/system/test/imap")
async def test_imap(request: Request, user: User = Depends(require_superadmin)):
    """Test IMAP login against given host/user/pass."""
    import imaplib
    form = await request.form()
    host = (form.get("host") or "").strip()
    port = int(form.get("port") or 993)
    username = (form.get("user") or "").strip()
    password = (form.get("pass") or "").strip()
    use_ssl = form.get("ssl") in ("on", "true", "1", None)
    if not host or not username or not password:
        return {"ok": False, "msg": "Host, User und Passwort sind nötig."}
    try:
        if use_ssl:
            cli = imaplib.IMAP4_SSL(host, port, timeout=20)
        else:
            cli = imaplib.IMAP4(host, port, timeout=20)
        cli.login(username, password)
        status, mailboxes = cli.list()
        cli.logout()
        if status == "OK":
            return {"ok": True, "msg": f"Login erfolgreich · {len(mailboxes)} Mailbox(en) gefunden."}
        return {"ok": False, "msg": f"Login OK, aber LIST scheiterte: {status}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"IMAP-Fehler: {e}"}


@router.post("/system/test/smtp-probe")
async def smtp_probe(request: Request, user: User = Depends(require_superadmin)):
    """Probe a SMTP host across the three common submission ports and report
    capabilities (STARTTLS / AUTH mechanisms) — helps diagnose AUTH/Port-Mismatch."""
    import smtplib, socket
    form = await request.form()
    host = (form.get("host") or "").strip()
    if not host:
        from ..config import get_settings
        host = (get_settings().smtp_host or "").strip()
    if not host:
        return {"ok": False, "msg": "Kein Host (SMTP_HOST nicht gesetzt und keiner übergeben)."}

    out = []
    for port in (25, 465, 587):
        line = f"Port {port}: "
        try:
            if port == 465:
                cli = smtplib.SMTP_SSL(host, port, timeout=6)
                cli.ehlo()
                line += "TLS-direkt OK · "
            else:
                cli = smtplib.SMTP(host, port, timeout=6)
                cli.ehlo()
                offers_starttls = cli.has_extn("starttls")
                if offers_starttls:
                    cli.starttls(); cli.ehlo()
                    line += "STARTTLS OK · "
                else:
                    line += "Klartext (kein STARTTLS) · "
            offers_auth = cli.has_extn("auth")
            if offers_auth:
                # esmtp_features['auth'] kann doppelt zurückkommen (multiple AUTH-Zeilen). Dedup.
                raw = cli.esmtp_features.get("auth", "").strip()
                mechs = " ".join(dict.fromkeys(raw.upper().split())) if raw else ""
                line += f"AUTH: {mechs or 'ja (Mechanismen unbekannt)'}"
            else:
                line += "AUTH: nein"
            cli.quit()
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            line += f"nicht erreichbar ({type(e).__name__})"
        except smtplib.SMTPException as e:
            line += f"SMTP-Error: {e}"
        except Exception as e:  # noqa: BLE001
            line += f"Error: {e}"
        out.append(line)
    return {"ok": True, "msg": f"Server-Capabilities für {host}:\n" + "\n".join(out)}


@router.post("/system/test/fernet")
def test_fernet(user: User = Depends(require_superadmin)):
    """Verify the current FERNET_KEY can encrypt + decrypt."""
    try:
        from cryptography.fernet import Fernet, InvalidToken
        from ..config import get_settings
        s = get_settings()
        if not s.fernet_key:
            return {"ok": False, "msg": "FERNET_KEY ist nicht gesetzt."}
        f = Fernet(s.fernet_key.encode())
        token = f.encrypt(b"probe")
        out = f.decrypt(token)
        if out == b"probe":
            return {"ok": True, "msg": "Fernet OK · Encrypt/Decrypt-Roundtrip erfolgreich."}
        return {"ok": False, "msg": "Roundtrip-Mismatch."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"Fehler: {e}"}
