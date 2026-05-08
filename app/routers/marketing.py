from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CustomerProfile, Tenant, TenantSettings, User
from ..security import hash_password, make_token
from ..templating import render

router = APIRouter()


# Demo-Tenant-Konfiguration -- isoliert vom echten Default-Tenant.
# Das Passwort ist absichtlich hart codiert (nicht geheim) -- es ist eine
# oeffentliche Demo, jeder klickt auf "Live-Demo" und wird automatisch
# eingeloggt. Der User hat is_admin=true (damit er navigieren kann), ist aber
# kein Superadmin (kann keine Tenants/User systemweit anlegen).
DEMO_TENANT_SLUG = "demo"
DEMO_TENANT_NAME = "Demo-Tenant"
DEMO_USER_EMAIL = "demo@dmarc-geeks.ch"


def _ensure_demo(db: Session) -> User:
    """Garantiert: Demo-Tenant + Demo-User + 30 Tage Demo-Daten existieren.
    Idempotent -- mehrmaliges Aufrufen fuegt nichts doppelt hinzu."""
    from scripts.seed_demo import seed_tenant

    tenant = db.execute(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG)).scalars().first()
    if tenant is None:
        tenant = Tenant(name=DEMO_TENANT_NAME, slug=DEMO_TENANT_SLUG)
        db.add(tenant)
        db.flush()
    if tenant.settings is None:
        db.add(TenantSettings(tenant_id=tenant.id, brand_color="#7c3aed"))
    if db.get(CustomerProfile, tenant.id) is None:
        db.add(CustomerProfile(tenant_id=tenant.id))
    db.commit()

    user = db.execute(select(User).where(User.email == DEMO_USER_EMAIL)).scalars().first()
    if user is None:
        user = User(
            email=DEMO_USER_EMAIL,
            password_hash=hash_password(make_token()),  # password unused for demo
            tenant_id=tenant.id,
            is_admin=True,
            is_superadmin=False,
        )
        db.add(user)
        db.commit()

    seed_tenant(db, tenant, days=30, reset=False)
    return user


@router.get("/demo")
def demo_signin(request: Request, db: Session = Depends(get_db)):
    """Public live demo -- creates demo tenant + user + data on first hit, then logs in."""
    user = _ensure_demo(db)
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["flash"] = {
        "kind": "ok",
        "text": "🎯 Demo-Modus aktiv. Du siehst 3 Beispiel-Domains mit 30 Tagen Reports. "
                "Klick dich durch, alles ist live. Logout via Profil-Menue.",
    }
    return RedirectResponse("/dashboard", status_code=303)


# ============================================================================
# Lead-Formular -- ersetzt die mailto: Buttons quer durch die Marketing-Site.
# ============================================================================

# Vordefinierte Topics (URL: /kontakt?topic=demo) -- erlauben pre-fill von der
# CTA-Stelle. Default = "Anfrage" wenn nicht angegeben.
_TOPIC_LABELS = {
    "demo": "Persönliche Demo",
    "dmarc": "DMARC-Einrichtung",
    "dmarc-quickstart": "DMARC Quickstart",
    "dmarc-reise": "Vollständige DMARC-Reise",
    "spf-dkim": "SPF/DKIM-Audit",
    "m365": "Microsoft 365 Hardening",
    "m365-threat": "M365 Threat-Hardening",
    "seppmail": "SEPPmail",
    "hin": "HIN-Einrichtung",
    "hin-stack": "Gesundheits-Stack komplett",
    "agency": "Agency-Plan",
    "reseller": "Reseller-Plan",
    "enterprise": "Enterprise-Plan",
    "reseller-pilot": "Reseller-Pilot",
    "dpa": "AVV / DPA / Auftragsverarbeitung",
    "mail-check": "Mail-Health-Check Erstgespräch",
    "general": "Anfrage",
}


def _topic_label(slug: str) -> str:
    return _TOPIC_LABELS.get((slug or "").strip().lower(), _TOPIC_LABELS["general"])


@router.get("/kontakt")
def contact_form(request: Request, topic: str = "general", domain: str = "", sent: int = 0):
    """Lead-Formular -- ersetzt mailto:-Links quer durch die Marketing-Site."""
    return render(
        request, "kontakt.html",
        user=None, tenant=None, active=None,
        topic=topic.strip().lower() or "general",
        topic_label=_topic_label(topic),
        prefill_domain=(domain or "").strip(),
        topics=_TOPIC_LABELS,
        sent=bool(sent), error=None,
    )


@router.post("/kontakt")
async def contact_submit(request: Request, db: Session = Depends(get_db)):
    """Sendet die Anfrage an SMTP_FROM (Operator-Postfach)."""
    from .. import mail as mail_mod
    from ..config import get_settings
    from ..rate_limit import mail_limiter

    form = await request.form()
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip().lower()
    company = (form.get("company") or "").strip()
    phone = (form.get("phone") or "").strip()
    message = (form.get("message") or "").strip()
    topic = (form.get("topic") or "general").strip().lower()
    honeypot = (form.get("website") or "").strip()  # bots fill this

    # Honeypot: Bots tappen rein
    if honeypot:
        return RedirectResponse("/kontakt?sent=1", status_code=303)

    # Validierung
    errors = []
    if len(name) < 2:
        errors.append("Bitte Namen angeben.")
    if "@" not in email or "." not in email or len(email) < 6:
        errors.append("Bitte gültige E-Mail-Adresse angeben.")
    if len(message) < 10:
        errors.append("Nachricht zu kurz (mind. 10 Zeichen).")
    if errors:
        return render(
            request, "kontakt.html",
            user=None, tenant=None, active=None,
            topic=topic, topic_label=_topic_label(topic),
            prefill_domain="", topics=_TOPIC_LABELS,
            sent=False, error=" ".join(errors),
            posted_name=name, posted_email=email,
            posted_company=company, posted_phone=phone, posted_message=message,
        )

    # Rate-Limit pro IP -- 5 Mails / 10 min
    ip = request.client.host if request.client else "anon"
    if not mail_limiter.take(f"contact:{ip}"):
        return render(
            request, "kontakt.html",
            user=None, tenant=None, active=None,
            topic=topic, topic_label=_topic_label(topic),
            prefill_domain="", topics=_TOPIC_LABELS,
            sent=False, error="Zu viele Anfragen von dieser IP — bitte einen Moment warten.",
            posted_name=name, posted_email=email,
            posted_company=company, posted_phone=phone, posted_message=message,
        )

    # Mail bauen + an Operator (SMTP_FROM) schicken
    s = get_settings()
    op_recipient = s.smtp_from or "operator@localhost"
    subject = f"[Anfrage: {_topic_label(topic)}] {name}"
    text_body = (
        f"Neue Anfrage über dmarc-geeks.ch\n\n"
        f"Thema:    {_topic_label(topic)} ({topic})\n"
        f"Name:     {name}\n"
        f"E-Mail:   {email}\n"
        f"Firma:    {company or '—'}\n"
        f"Telefon:  {phone or '—'}\n"
        f"IP:       {ip}\n\n"
        f"Nachricht:\n"
        f"-----------\n"
        f"{message}\n"
        f"-----------\n"
    )
    html_body = (
        f"<h2>Neue Anfrage über dmarc-geeks.ch</h2>"
        f"<p><strong>Thema:</strong> {_topic_label(topic)} <code>({topic})</code></p>"
        f"<table style='border-collapse:collapse;font:14px sans-serif'>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>Name</td><td>{name}</td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>E-Mail</td><td><a href='mailto:{email}'>{email}</a></td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>Firma</td><td>{company or '—'}</td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>Telefon</td><td>{phone or '—'}</td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>IP</td><td>{ip}</td></tr>"
        f"</table>"
        f"<p><strong>Nachricht:</strong></p>"
        f"<blockquote style='border-left:3px solid #2563eb;padding:8px 16px;background:#f1f5f9;color:#0f172a;white-space:pre-wrap'>{message}</blockquote>"
    )

    # Reply-To = lead's mail -> Operator kann direkt aus dem Postfach antworten
    sent = mail_mod.send_mail(to=op_recipient, subject=subject,
                               text=text_body, html=html_body, reply_to=email)

    if not sent:
        # SMTP nicht konfiguriert oder fehlgeschlagen -> wir loggen's, zeigen aber
        # dem User keinen 500er, sondern eine ehrliche "wir konnten gerade nicht
        # zustellen" Antwort. Audit-Trail im Log.
        return render(
            request, "kontakt.html",
            user=None, tenant=None, active=None,
            topic=topic, topic_label=_topic_label(topic),
            prefill_domain="", topics=_TOPIC_LABELS,
            sent=False,
            error="Mail-Versand temporaer nicht moeglich. Bitte schreib uns direkt an "
                  + op_recipient + " — wir melden uns innerhalb 24h.",
            posted_name=name, posted_email=email,
            posted_company=company, posted_phone=phone, posted_message=message,
        )

    return RedirectResponse(f"/kontakt?sent=1&topic={topic}", status_code=303)


@router.get("/")
def root(request: Request):
    """Marketing for anonymous users; redirect to /dashboard for logged-in,
    preserving any query string (so old bookmarks like /?domain_id=X still work)."""
    if request.session.get("user_id"):
        qs = request.url.query
        target = "/dashboard" + (f"?{qs}" if qs else "")
        return RedirectResponse(target, status_code=303)
    return render(request, "marketing.html", user=None, tenant=None, active=None)


@router.get("/about")
def about(request: Request):
    return render(request, "marketing.html", user=None, tenant=None, active=None)


@router.get("/preise")
def pricing(request: Request):
    return render(request, "marketing.html", user=None, tenant=None, active=None)


@router.get("/compliance")
def compliance(request: Request):
    return render(request, "compliance.html", user=None, tenant=None, active=None)


@router.get("/services")
def services(request: Request):
    return render(request, "services.html", user=None, tenant=None, active=None)


@router.get("/services/dmarc")
def services_dmarc(request: Request):
    return render(request, "services/dmarc.html", user=None, tenant=None, active=None)


@router.get("/services/m365")
def services_m365(request: Request):
    return render(request, "services/m365.html", user=None, tenant=None, active=None)


@router.get("/services/seppmail")
def services_seppmail(request: Request):
    return render(request, "services/seppmail.html", user=None, tenant=None, active=None)


@router.get("/services/hin")
def services_hin(request: Request):
    return render(request, "services/hin.html", user=None, tenant=None, active=None)


@router.get("/wissen")
def wissen(request: Request):
    return render(request, "wissen.html", user=None, tenant=None, active=None)


@router.get("/dkim-check")
def dkim_check_tool(request: Request, domain: str = "", selector: str = ""):
    """Free DKIM-Inspector tool — public, no auth."""
    from ..dns_utils import lookup_dkim_with_details, parse_dkim_record, get_txt_records, DKIM_SELECTORS
    domain = (domain or "").strip().lower().rstrip(".")
    if domain.startswith("http://"): domain = domain[7:]
    if domain.startswith("https://"): domain = domain[8:]
    if "/" in domain: domain = domain.split("/", 1)[0]
    selector = (selector or "").strip().lower()

    results = None
    summary_msg = None
    if domain and "." in domain:
        if selector:
            # Manual single-selector check
            txts = get_txt_records(f"{selector}._domainkey.{domain}")
            results = []
            for t in txts:
                low = t.lower()
                if "v=dkim1" in low or "k=rsa" in low or "k=ed25519" in low or "p=" in low:
                    p = parse_dkim_record(t)
                    p["selector"] = selector
                    p["fqdn"] = f"{selector}._domainkey.{domain}"
                    results.append(p)
            if not results:
                summary_msg = f"Kein DKIM-Record auf {selector}._domainkey.{domain} — Selektor existiert nicht oder Domain hat ihn nicht (mehr) konfiguriert."
        else:
            # Auto-discover selectors
            results = lookup_dkim_with_details(domain)
            if not results:
                summary_msg = (f"Keine DKIM-Selektoren gefunden bei {len(DKIM_SELECTORS)} probierten Namen. "
                               "Möglich: dein Provider nutzt einen exotischen Selektor — gib ihn unten manuell ein.")

    return render(request, "tools/dkim_check.html", user=None, tenant=None, active=None,
                  query_domain=domain, query_selector=selector,
                  results=results, summary_msg=summary_msg,
                  selector_count=len(DKIM_SELECTORS))


@router.get("/report-viewer")
def report_viewer(request: Request):
    """Free XML-to-Human DMARC report converter — public, no auth."""
    return render(request, "tools/report_viewer.html", user=None, tenant=None, active=None)


@router.post("/report-viewer/parse")
async def report_viewer_parse(request: Request):
    """Server-side parsing of pasted/uploaded XML."""
    from fastapi.responses import JSONResponse
    form = await request.form()
    xml_text = (form.get("xml") or "").strip()
    if not xml_text:
        # Maybe file upload
        upload = form.get("file")
        if upload and hasattr(upload, "read"):
            content = await upload.read() if callable(getattr(upload, "read", None)) else upload.read()
            if isinstance(content, bytes):
                # Detect gz/zip if any
                try:
                    xml_text = content.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    xml_text = ""
    if not xml_text:
        return JSONResponse({"ok": False, "error": "Kein XML-Inhalt erhalten."}, status_code=400)

    try:
        parsed = _parse_dmarc_xml_for_viewer(xml_text)
        return JSONResponse({"ok": True, "report": parsed})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"Parse-Fehler: {e}"}, status_code=400)


def _parse_dmarc_xml_for_viewer(xml_text: str) -> dict:
    """Parse a DMARC RUA XML report into a viewer-friendly dict."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text.strip())
    out: dict = {"meta": {}, "policy": {}, "records": []}

    # report_metadata
    md = root.find("report_metadata")
    if md is not None:
        out["meta"] = {
            "org_name": (md.findtext("org_name") or "").strip(),
            "email": (md.findtext("email") or "").strip(),
            "report_id": (md.findtext("report_id") or "").strip(),
            "date_begin": (md.findtext("date_range/begin") or "").strip(),
            "date_end": (md.findtext("date_range/end") or "").strip(),
        }
        # Convert epoch to readable
        from datetime import datetime, timezone
        for k in ("date_begin", "date_end"):
            v = out["meta"].get(k)
            if v and v.isdigit():
                out["meta"][k + "_iso"] = datetime.fromtimestamp(int(v), timezone.utc).isoformat()

    # policy_published
    pp = root.find("policy_published")
    if pp is not None:
        out["policy"] = {
            "domain": (pp.findtext("domain") or "").strip(),
            "adkim": (pp.findtext("adkim") or "").strip(),
            "aspf": (pp.findtext("aspf") or "").strip(),
            "p": (pp.findtext("p") or "").strip(),
            "sp": (pp.findtext("sp") or "").strip(),
            "pct": (pp.findtext("pct") or "").strip(),
            "fo": (pp.findtext("fo") or "").strip(),
        }

    # records
    for rec in root.findall("record"):
        row = rec.find("row")
        if row is None:
            continue
        identifiers = rec.find("identifiers")
        auth = rec.find("auth_results")
        record_data = {
            "source_ip": (row.findtext("source_ip") or "").strip(),
            "count": int(row.findtext("count") or 0),
            "disposition": (row.findtext("policy_evaluated/disposition") or "").strip(),
            "dkim_eval": (row.findtext("policy_evaluated/dkim") or "").strip(),
            "spf_eval": (row.findtext("policy_evaluated/spf") or "").strip(),
            "header_from": "",
            "envelope_from": "",
            "auth_dkim": [],
            "auth_spf": [],
        }
        if identifiers is not None:
            record_data["header_from"] = (identifiers.findtext("header_from") or "").strip()
            record_data["envelope_from"] = (identifiers.findtext("envelope_from") or "").strip()
        if auth is not None:
            for d in auth.findall("dkim"):
                record_data["auth_dkim"].append({
                    "domain": (d.findtext("domain") or "").strip(),
                    "selector": (d.findtext("selector") or "").strip(),
                    "result": (d.findtext("result") or "").strip(),
                })
            for s in auth.findall("spf"):
                record_data["auth_spf"].append({
                    "domain": (s.findtext("domain") or "").strip(),
                    "result": (s.findtext("result") or "").strip(),
                })
        out["records"].append(record_data)

    # Aggregate stats
    out["stats"] = {
        "total_messages": sum(r["count"] for r in out["records"]),
        "unique_sources": len({r["source_ip"] for r in out["records"]}),
        "pass_count": sum(r["count"] for r in out["records"]
                          if r["dkim_eval"] == "pass" or r["spf_eval"] == "pass"),
        "fail_count": sum(r["count"] for r in out["records"]
                          if r["dkim_eval"] != "pass" and r["spf_eval"] != "pass"),
    }
    if out["stats"]["total_messages"]:
        out["stats"]["pass_rate"] = round(100 * out["stats"]["pass_count"] / out["stats"]["total_messages"], 1)
    else:
        out["stats"]["pass_rate"] = 0.0

    return out
