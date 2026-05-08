from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _fmt_dt(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    return value.strftime(fmt)


def _fmt_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _brand_color(tenant) -> str:
    if tenant is None:
        return "#2563eb"
    # Reseller branding takes precedence
    reseller = getattr(tenant, "reseller", None)
    if reseller is not None and not getattr(reseller, "is_platform", False):
        return reseller.brand_color or "#2563eb"
    settings = getattr(tenant, "settings", None)
    if settings is None:
        return "#2563eb"
    return settings.brand_color or "#2563eb"


def _brand_app_name(tenant) -> str:
    if tenant is None:
        return "DMARC Geeks"
    reseller = getattr(tenant, "reseller", None)
    if reseller is not None and not getattr(reseller, "is_platform", False):
        return reseller.app_name or "DMARC Geeks"
    return "DMARC Geeks"


def _brand_logo_url(tenant) -> str | None:
    if tenant is None:
        return None
    reseller = getattr(tenant, "reseller", None)
    if reseller is not None and not getattr(reseller, "is_platform", False):
        return reseller.logo_url
    return None


def _from_json(value):
    """Parse a JSON string. Returns None on failure rather than crashing the template."""
    import json as _json
    if not value:
        return None
    try:
        return _json.loads(value)
    except (ValueError, TypeError):
        return None


def _bl_delist(zone: str, ip: str, kind: str = "remove") -> str:
    from .blacklist import delisting_url
    return delisting_url(zone, ip, kind)


templates.env.filters["dt"] = _fmt_dt
templates.env.filters["num"] = _fmt_int
templates.env.filters["from_json"] = _from_json
templates.env.globals["brand_color"] = _brand_color
templates.env.globals["brand_app_name"] = _brand_app_name
templates.env.globals["brand_logo_url"] = _brand_logo_url
templates.env.globals["bl_delist"] = _bl_delist


def _delegation_record_name(customer_domain: str, our_zone: str) -> str:
    from .hetzner_dns import delegation_record_name
    return delegation_record_name(customer_domain, our_zone)


templates.env.globals["delegation_record_name"] = _delegation_record_name


def render(request: Request, template: str, **context):
    return templates.TemplateResponse(request, template, context)
