from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ..dependencies import require_user
from ..dns_utils import full_dns_check, score_check
from ..models import User
from ..templating import render

router = APIRouter()


def _normalize_domain(raw: Optional[str]) -> str:
    d = (raw or "").strip().lower().rstrip(".")
    # strip http(s):// and trailing path if user pasted a URL
    if d.startswith("http://"):
        d = d[7:]
    if d.startswith("https://"):
        d = d[8:]
    if "/" in d:
        d = d.split("/", 1)[0]
    return d


@router.get("/dns-check")
def dns_check(
    request: Request,
    domain: Optional[str] = Query(None),
    user: User = Depends(require_user),
):
    domain = _normalize_domain(domain)
    result = full_dns_check(domain) if domain and "." in domain else None
    score = score_check(result) if result else None
    return render(
        request,
        "dns_check.html",
        user=user,
        tenant=user.tenant,
        query_domain=domain,
        result=result,
        score=score,
        active="dns-check",
    )


# ---------- Public health-check (für Marketing + Generator-Inline) ----------

@router.get("/check")
def public_check(
    request: Request,
    domain: Optional[str] = Query(None),
    print_view: bool = Query(False, alias="print"),
):
    """Öffentlich zugänglicher Mail-Health-Check für Marketing-Besucher."""
    dom = _normalize_domain(domain)
    result = full_dns_check(dom) if dom and "." in dom else None
    score = score_check(result) if result else None
    if dom and "." in dom:
        # Lead-Signal: Domain wurde gecheckt -> einmalige Notification an Operator
        from .marketing import notify_domain_check
        notify_domain_check(request, tool="mail-health-check", domain=dom)
    template = "mailcheck_print.html" if print_view and result else "mailcheck.html"
    return render(
        request,
        template,
        user=None,
        tenant=None,
        active=None,
        query_domain=dom,
        result=result,
        score=score,
    )


@router.get("/api/check")
def public_check_json(domain: str = Query(...)):
    """JSON-API für Inline-Check im Generator etc."""
    dom = _normalize_domain(domain)
    if not dom or "." not in dom:
        return JSONResponse({"error": "invalid_domain"}, status_code=400)
    result = full_dns_check(dom)
    score = score_check(result)
    return {"domain": dom, "result": result, "score": score}
