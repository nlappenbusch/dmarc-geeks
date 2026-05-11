import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import Base, SessionLocal, engine
from .middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from .models import CustomerProfile, Reseller, Tenant, TenantSettings, User
from .routers import (admin, api, api_keys, audit as audit_router, auth, auth_extra, dashboard,
                      dns_check, domains, generator, help as help_router, mail_tester, mailboxes, marketing,
                      report_pdf, reports, reseller as reseller_router,
                      settings as settings_router, sources, tags, upload, users,
                      webhooks as webhooks_router)
from .scheduler import start_scheduler, stop_scheduler
from .security import hash_password
from .templating import render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


def _migrate_alter_columns() -> None:
    """Idempotent ALTER TABLE for columns added after initial release.

    Only runs ALTERs that aren't already present. Works for SQLite + Postgres.
    """
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "tenants" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("tenants")}
        if "reseller_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN reseller_id INTEGER"))
            log.info("migrated: tenants.reseller_id added")
    if "users" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "is_reseller_admin" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_reseller_admin BOOLEAN DEFAULT 0 NOT NULL"))
            log.info("migrated: users.is_reseller_admin added")
    if "mailboxes" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("mailboxes")}
        if "reseller_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE mailboxes ADD COLUMN reseller_id INTEGER"))
            log.info("migrated: mailboxes.reseller_id added")
    if "blacklist_checks" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("blacklist_checks")}
        if "alerted_event" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE blacklist_checks ADD COLUMN alerted_event VARCHAR(32)"))
            log.info("migrated: blacklist_checks.alerted_event added")
        if "alerted_at" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE blacklist_checks ADD COLUMN alerted_at TIMESTAMP"))
            log.info("migrated: blacklist_checks.alerted_at added")
    if "domains" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("domains")}
        if "auth_record_managed" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE domains ADD COLUMN auth_record_managed BOOLEAN DEFAULT 0 NOT NULL"))
            log.info("migrated: domains.auth_record_managed added")
        if "auth_record_at" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE domains ADD COLUMN auth_record_at TIMESTAMP"))
            log.info("migrated: domains.auth_record_at added")
        if "managed_dmarc" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE domains ADD COLUMN managed_dmarc BOOLEAN DEFAULT 0 NOT NULL"))
            log.info("migrated: domains.managed_dmarc added")
        if "managed_policy" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE domains ADD COLUMN managed_policy VARCHAR(500)"))
            log.info("migrated: domains.managed_policy added")
        if "managed_at" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE domains ADD COLUMN managed_at TIMESTAMP"))
            log.info("migrated: domains.managed_at added")


def _bootstrap_superadmin() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        # ensure default platform reseller exists
        platform = db.execute(select(Reseller).where(Reseller.is_platform.is_(True))).scalars().first()
        if platform is None:
            platform = Reseller(name="Plattform", slug="platform", is_platform=True,
                                  app_name="DMARC Aggregator", brand_color="#2563eb",
                                  plan="reseller_plus", seat_limit=10000)
            db.add(platform)
            db.flush()

        # ensure TenantSettings + CustomerProfile rows exist; assign tenants without reseller to platform
        for t in db.execute(select(Tenant)).scalars():
            if t.settings is None:
                db.add(TenantSettings(tenant_id=t.id))
            if db.get(CustomerProfile, t.id) is None:
                db.add(CustomerProfile(tenant_id=t.id))
            if t.reseller_id is None:
                t.reseller_id = platform.id
        db.commit()

        if db.execute(select(User.id)).scalars().first():
            return
        tenant = Tenant(name=settings.default_tenant_name, slug="default")
        db.add(tenant)
        db.flush()
        db.add(TenantSettings(tenant_id=tenant.id))
        db.add(CustomerProfile(tenant_id=tenant.id))
        sa = User(
            email=settings.superadmin_email.lower().strip(),
            password_hash=hash_password(settings.superadmin_password),
            tenant_id=tenant.id,
            is_admin=True,
            is_superadmin=True,
        )
        db.add(sa)
        db.commit()
        log.info("Bootstrapped superadmin %s and tenant %s", sa.email, tenant.name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    _migrate_alter_columns()
    _bootstrap_superadmin()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DMARC Aggregator", lifespan=lifespan)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    if settings.trusted_proxies:
        from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: F401
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(auth.router)
    app.include_router(auth_extra.router)
    app.include_router(dashboard.router)
    app.include_router(domains.router)
    app.include_router(reports.router)
    app.include_router(upload.router)
    app.include_router(mailboxes.router)
    app.include_router(users.router)
    app.include_router(api_keys.router)
    app.include_router(webhooks_router.router)
    app.include_router(tags.router)
    app.include_router(settings_router.router)
    app.include_router(audit_router.router)
    app.include_router(reseller_router.router)
    app.include_router(report_pdf.router)
    app.include_router(admin.router)
    app.include_router(help_router.router)
    app.include_router(generator.router)
    app.include_router(dns_check.router)
    app.include_router(sources.router)
    app.include_router(marketing.router)
    app.include_router(mail_tester.router)
    app.include_router(api.router)

    @app.get("/healthz")
    def healthz():
        from sqlalchemy import text
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            from fastapi.responses import JSONResponse
            return JSONResponse({"ok": False, "error": str(e)}, status_code=503)

    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401 and not request.url.path.startswith("/api/"):
            return RedirectResponse("/login", status_code=303)
        accept = request.headers.get("accept", "")
        if "text/html" in accept and exc.status_code in (403, 404, 500):
            resp = render(request, "error.html", status_code=exc.status_code,
                          detail=str(exc.detail), user=None, tenant=None, active=None)
            resp.status_code = exc.status_code
            return resp
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def generic_exc_handler(request: Request, exc: Exception):
        log.exception("Unhandled error: %s", exc)
        accept = request.headers.get("accept", "")
        # Debug-Mode: kompletter Traceback in der Browser-Antwort
        if get_settings().debug_traceback and "text/html" in accept:
            import html as _html
            import traceback as _tb
            from fastapi.responses import HTMLResponse
            tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
            rid = request.headers.get("x-request-id", "-")
            body = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>500 - {_html.escape(type(exc).__name__)}</title>"
                "<style>"
                "body{font:14px/1.5 -apple-system,Inter,sans-serif;background:#0f172a;"
                "color:#f1f5f9;margin:0;padding:24px}"
                "h1{color:#f87171;margin:0 0 4px;font-size:20px}"
                "h2{color:#fbbf24;font-size:13px;text-transform:uppercase;"
                "letter-spacing:.05em;margin:24px 0 8px}"
                "pre{background:#1e293b;border-radius:6px;padding:16px;overflow:auto;"
                "border-left:3px solid #f87171;white-space:pre-wrap;"
                "font:12px/1.5 Menlo,Consolas,monospace}"
                ".meta{color:#94a3b8;font-size:12px;margin-bottom:16px}"
                ".warn{background:#7c2d12;color:#fed7aa;padding:8px 12px;border-radius:4px;"
                "display:inline-block;margin-bottom:16px;font-size:12px}"
                "</style></head><body>"
                "<div class='warn'>DEBUG_TRACEBACK ist aktiv -- in Produktion ausschalten</div>"
                f"<h1>500 - {_html.escape(type(exc).__name__)}</h1>"
                f"<div class='meta'>{_html.escape(str(exc))[:500]}</div>"
                f"<div class='meta'>{_html.escape(request.method)} "
                f"{_html.escape(request.url.path)} &middot; request-id: "
                f"{_html.escape(rid)}</div>"
                f"<h2>Traceback</h2><pre>{_html.escape(tb_text)}</pre>"
                "</body></html>"
            )
            return HTMLResponse(body, status_code=500)
        if "text/html" in accept:
            resp = render(request, "error.html", status_code=500,
                          detail="Interner Fehler.", user=None, tenant=None, active=None)
            resp.status_code = 500
            return resp
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)

    return app


app = create_app()
