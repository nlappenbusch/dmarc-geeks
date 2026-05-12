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
    "bimi": "BIMI Setup (CMC)",
    "bimi-vmc": "BIMI Setup mit VMC (Verified-Tick)",
    "agency": "Agency-Plan",
    "reseller": "Reseller-Plan",
    "enterprise": "Enterprise-Plan",
    "reseller-pilot": "MSP-Whitelabel-Pilot",
    "msp-enterprise": "MSP-Enterprise / Self-Hosting (Quote)",
    "audit": "Mail-Health-Audit (CHF 490)",
    "foundation": "Mail-Security Foundation (CHF 1'990)",
    "pro": "Mail-Security Pro+ mit BIMI",
    "starter": "Mail-Health-Audit",  # alter Slug -> Audit (Rueckwaerts-Kompat)
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

    # === Mail 1: Operator-Notification ===
    # Empfaenger: SMTP_FROM (Postfach) + SUPERADMIN_EMAIL falls abweichend.
    # User-Setup: SMTP_FROM=service@dmarc-geeks.ch, SUPERADMIN_EMAIL=nlappenbusch@gmail.com
    # -> beide bekommen die Anfrage, Operator UND Inhaber.
    s = get_settings()
    op_recipients = _operator_recipients(s)

    op_subject = f"[Anfrage: {_topic_label(topic)}] {name}"
    op_text = (
        f"Neue Anfrage ueber dmarc-geeks.ch\n\n"
        f"Thema:    {_topic_label(topic)} ({topic})\n"
        f"Name:     {name}\n"
        f"E-Mail:   {email}\n"
        f"Firma:    {company or '-'}\n"
        f"Telefon:  {phone or '-'}\n"
        f"IP:       {ip}\n\n"
        f"Nachricht:\n-----------\n{message}\n-----------\n\n"
        f"Antworten an diese Mail gehen direkt an: {email}\n"
    )
    op_html = (
        f"<h2 style='margin:0 0 14px 0'>Neue Anfrage ueber dmarc-geeks.ch</h2>"
        f"<p style='margin:0 0 14px 0'><strong>Thema:</strong> {_topic_label(topic)} "
        f"<code>({topic})</code></p>"
        f"<table style='border-collapse:collapse;font:14px sans-serif'>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>Name</td><td>{name}</td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>E-Mail</td>"
        f"<td><a href='mailto:{email}'>{email}</a></td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>Firma</td><td>{company or '-'}</td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>Telefon</td><td>{phone or '-'}</td></tr>"
        f"<tr><td style='padding:4px 12px 4px 0;color:#64748b'>IP</td><td>{ip}</td></tr>"
        f"</table>"
        f"<p style='margin:18px 0 6px 0'><strong>Nachricht:</strong></p>"
        f"<blockquote style='border-left:3px solid #2563eb;padding:10px 16px;"
        f"background:#f1f5f9;color:#0f172a;white-space:pre-wrap;"
        f"font:14px sans-serif;border-radius:0 6px 6px 0'>{message}</blockquote>"
    )

    op_sent = mail_mod.send_mail(
        to=op_recipients, subject=op_subject,
        text=op_text, html=op_html, reply_to=email,
    )

    # === Mail 2: Lead-Confirmation (fancy HTML mit Branding) ===
    lead_html = mail_mod.render_email(
        "contact_confirmation",
        name=name, email=email, company=company,
        topic_label=_topic_label(topic), message=message,
        base_url=s.base_url.rstrip("/"),
        brand_name="DMARC Geeks", brand_color="#2563eb", brand_logo=None,
    )
    lead_text = (
        f"Hallo {name},\n\n"
        f"danke fuer deine Anfrage zu \"{_topic_label(topic)}\" auf dmarc-geeks.ch!\n"
        f"Wir melden uns innerhalb von 24 Stunden bei dir per E-Mail.\n\n"
        f"Deine Nachricht:\n-----------\n{message}\n-----------\n\n"
        f"Inzwischen kannst du dir die Live-Demo ansehen:\n"
        f"{s.base_url.rstrip('/')}/demo\n\n"
        f"Antworten auf diese Mail gehen direkt in unser Postfach -- schreib einfach "
        f"zurueck wenn du etwas vergessen hast.\n\n"
        f"Liebe Gruesse\nDMARC Geeks\n"
    )
    # Lead-Confirmation: kein Reply-To noetig, Replies gehen via SMTP_FROM zurueck an uns.
    mail_mod.send_mail(
        to=email, subject="Wir haben deine Anfrage erhalten - DMARC Geeks",
        text=lead_text, html=lead_html,
    )

    # Operator-Mail ist die "Pflicht-Sendung" -- wenn die scheitert, Fehler zeigen.
    sent = op_sent

    if not sent:
        # SMTP nicht konfiguriert oder fehlgeschlagen -- ehrliche Fallback-Antwort
        return render(
            request, "kontakt.html",
            user=None, tenant=None, active=None,
            topic=topic, topic_label=_topic_label(topic),
            prefill_domain="", topics=_TOPIC_LABELS,
            sent=False,
            error="Mail-Versand temporaer nicht moeglich. Bitte schreib uns direkt an "
                  + op_recipients[0] + " - wir melden uns innerhalb 24h.",
            posted_name=name, posted_email=email,
            posted_company=company, posted_phone=phone, posted_message=message,
        )

    return RedirectResponse(f"/kontakt?sent=1&topic={topic}", status_code=303)


# ============================================================================
# Lead-Notify bei Domain-Eingabe in oeffentlichen Tools (Mail-Check, DKIM Insp.)
# ============================================================================

def _operator_recipients(s) -> list[str]:
    """SMTP_FROM + SUPERADMIN_EMAIL + LEAD_NOTIFY_EMAILS, dedupliziert.

    SMTP_FROM = Operator-Postfach (z.B. service@firma.ch)
    SUPERADMIN_EMAIL = Login-Adresse (auch im Loop)
    LEAD_NOTIFY_EMAILS = komma-separierte Liste zusaetzlicher Lead-Empfaenger
                        (z.B. private Gmail, CRM-Inbox, ...)
    """
    rec: list[str] = []
    seen: set[str] = set()

    def _add(email: str) -> None:
        e = (email or "").strip()
        if not e:
            return
        if e.lower() in seen:
            return
        seen.add(e.lower())
        rec.append(e)

    _add(s.smtp_from)
    _add(s.superadmin_email)
    for e in (s.lead_notify_emails or "").split(","):
        _add(e)
    return rec or ["operator@localhost"]


def _reverse_dns(ip: str) -> str:
    """Best-effort PTR-Lookup mit kurzem Timeout. Gibt '-' zurueck wenn fehlt."""
    if not ip or ip in ("-", "127.0.0.1", "::1") or ip.startswith("192.168.") or ip.startswith("10."):
        return "-"
    try:
        import dns.resolver, dns.reversename
        rev = dns.reversename.from_address(ip)
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = ["1.1.1.1", "8.8.8.8"]
        r.lifetime = 2.0
        r.timeout = 1.5
        ans = r.resolve(rev, "PTR", lifetime=2.0)
        return str(ans[0]).rstrip(".")
    except Exception:  # noqa: BLE001
        return "-"


def _parse_ua(ua: str) -> str:
    """Sehr leichtgewichtige UA-Parse: Browser + OS in Kurzform."""
    if not ua or ua == "-":
        return "-"
    ua_low = ua.lower()
    browser = "?"
    if "edg/" in ua_low: browser = "Edge"
    elif "chrome/" in ua_low and "chromium" not in ua_low: browser = "Chrome"
    elif "firefox/" in ua_low: browser = "Firefox"
    elif "safari/" in ua_low and "chrome" not in ua_low: browser = "Safari"
    elif "bot" in ua_low or "crawl" in ua_low or "spider" in ua_low: browser = "Bot"
    os_ = "?"
    if "windows" in ua_low: os_ = "Windows"
    elif "mac os x" in ua_low or "macintosh" in ua_low: os_ = "macOS"
    elif "android" in ua_low: os_ = "Android"
    elif "iphone" in ua_low or "ipad" in ua_low: os_ = "iOS"
    elif "linux" in ua_low: os_ = "Linux"
    return f"{browser} on {os_}"


def notify_domain_check(request: Request, tool: str, domain: str) -> None:
    """Schickt Lead-Notification ans Operator-Postfach, wenn jemand in einem
    oeffentlichen Tool eine Domain eingibt. Session-dedup: pro Browser-Session
    nur einmal pro (tool, domain) feuern -- Refreshes feuern nichts neu.
    Silent fail wenn SMTP nicht konfiguriert.
    """
    if not domain or "." not in domain:
        return
    domain = domain.strip().lower().rstrip(".")
    session_key = "lead_notified"
    notified = set(request.session.get(session_key, []))
    fp = f"{tool}::{domain}"
    if fp in notified:
        return
    notified.add(fp)
    request.session[session_key] = list(notified)[-50:]  # cap session size

    try:
        from datetime import datetime, timezone
        from .. import mail as mail_mod
        from ..config import get_settings
        s = get_settings()

        # Header-Mining: alle relevanten Infos aus dem Request ziehen
        ip = request.client.host if request.client else "-"
        # Hinter NPM/Reverse-Proxy steht die echte IP in X-Forwarded-For
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            real_ip = xff.split(",")[0].strip()
        else:
            real_ip = ip
        ua_raw = request.headers.get("user-agent", "-")
        ua_short = _parse_ua(ua_raw)
        ref = request.headers.get("referer", "-")
        lang = request.headers.get("accept-language", "-")
        host_hdr = request.headers.get("host", "-")
        ptr = _reverse_dns(real_ip)
        ts = datetime.now(timezone.utc)
        ts_iso = ts.isoformat(timespec="seconds")
        ts_local = ts.strftime("%d.%m.%Y %H:%M UTC")

        subject = f"[Lead] {domain} - {tool}"
        text = (
            f"Lead-Signal: jemand hat im Tool '{tool}' eine Domain getestet.\n\n"
            f"  Zeitpunkt:   {ts_local}\n"
            f"  Domain:      {domain}\n"
            f"  Tool:        {tool}\n"
            f"  IP:          {real_ip}\n"
            f"  PTR (rDNS):  {ptr}\n"
            f"  Browser/OS:  {ua_short}\n"
            f"  Sprache:     {lang}\n"
            f"  Referer:     {ref}\n"
            f"  User-Agent:  {ua_raw}\n"
            f"  Host:        {host_hdr}\n"
            f"  Direct IP:   {ip}{' (=XFF)' if ip == real_ip else ' (Reverse-Proxy)'}\n\n"
            f"-> Resultat oeffnen: https://dmarc-geeks.ch/check?domain={domain}\n"
            f"-> WHOIS:           https://www.whois.com/whois/{domain}\n"
            f"-> IP-Lookup:       https://www.abuseipdb.com/check/{real_ip}\n"
        )
        html = (
            f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
            f"style='border-collapse:collapse;font:14px -apple-system,Inter,sans-serif;color:#0f172a'>"
            f"<tr><td style='padding:0 0 12px 0'>"
            f"<div style='display:inline-block;background:linear-gradient(135deg,#2563eb,#7c3aed);"
            f"color:white;padding:6px 14px;border-radius:999px;font-size:12px;font-weight:600;"
            f"letter-spacing:.04em;text-transform:uppercase'>Lead-Signal</div></td></tr>"
            f"<tr><td style='padding:0 0 16px 0'><h2 style='margin:0;font-size:20px'>"
            f"<a href='https://dmarc-geeks.ch/check?domain={domain}' "
            f"style='color:#2563eb;text-decoration:none'>{domain}</a> "
            f"im <code style='background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:13px'>"
            f"{tool}</code> geprueft</h2>"
            f"<div style='color:#64748b;font-size:13px;margin-top:4px'>{ts_local}</div></td></tr>"
            f"<tr><td><table style='border-collapse:collapse;font-size:13.5px;width:100%'>"
            f"<tr><td style='padding:6px 14px 6px 0;color:#64748b;width:130px;vertical-align:top'>IP</td>"
            f"<td style='padding:6px 0;font-family:monospace'>{real_ip}</td></tr>"
            f"<tr><td style='padding:6px 14px 6px 0;color:#64748b;vertical-align:top'>Reverse-DNS</td>"
            f"<td style='padding:6px 0;font-family:monospace'>{ptr}</td></tr>"
            f"<tr><td style='padding:6px 14px 6px 0;color:#64748b;vertical-align:top'>Browser/OS</td>"
            f"<td style='padding:6px 0'>{ua_short}</td></tr>"
            f"<tr><td style='padding:6px 14px 6px 0;color:#64748b;vertical-align:top'>Sprache</td>"
            f"<td style='padding:6px 0'>{lang}</td></tr>"
            f"<tr><td style='padding:6px 14px 6px 0;color:#64748b;vertical-align:top'>Referer</td>"
            f"<td style='padding:6px 0'>"
            + (f"<a href='{ref}' style='color:#2563eb'>{ref}</a>" if ref.startswith("http") else ref)
            + f"</td></tr>"
            f"<tr><td style='padding:6px 14px 6px 0;color:#64748b;vertical-align:top'>User-Agent</td>"
            f"<td style='padding:6px 0;font-family:monospace;font-size:11.5px;color:#475569'>{ua_raw}</td></tr>"
            f"<tr><td style='padding:6px 14px 6px 0;color:#64748b;vertical-align:top'>Zeitpunkt</td>"
            f"<td style='padding:6px 0;font-family:monospace'>{ts_iso}</td></tr>"
            f"</table></td></tr>"
            f"<tr><td style='padding:18px 0 6px 0'>"
            f"<a href='https://dmarc-geeks.ch/check?domain={domain}' "
            f"style='display:inline-block;background:#2563eb;color:white;padding:10px 18px;"
            f"border-radius:8px;text-decoration:none;font-weight:600;margin-right:8px'>"
            f"-> Resultat ansehen</a>"
            f"<a href='https://www.whois.com/whois/{domain}' "
            f"style='display:inline-block;color:#64748b;padding:10px 12px;text-decoration:none;font-size:13px'>"
            f"WHOIS</a>"
            f"<a href='https://www.abuseipdb.com/check/{real_ip}' "
            f"style='display:inline-block;color:#64748b;padding:10px 12px;text-decoration:none;font-size:13px'>"
            f"IP-Lookup</a>"
            f"</td></tr></table>"
        )
        mail_mod.send_mail(
            to=_operator_recipients(s),
            subject=subject, text=text, html=html,
        )
    except Exception:  # noqa: BLE001
        # Lead-Notification darf NIE den User-Request crashen
        import logging
        logging.getLogger(__name__).warning("notify_domain_check failed", exc_info=True)


@router.get("/")
def root(request: Request):
    """Marketing for anonymous users; redirect to /dashboard for logged-in,
    preserving any query string (so old bookmarks like /?domain_id=X still work).

    Host-aware: wenn die Anfrage über mail-test.ch / www.mail-test.ch
    reinkommt, zeigen wir die Mail-Tester-fokussierte Landing statt der
    generischen Startseite. Das selbe Tool, anderer Brand-Funnel."""
    if request.session.get("user_id"):
        qs = request.url.query
        target = "/dashboard" + (f"?{qs}" if qs else "")
        return RedirectResponse(target, status_code=303)

    # Host-Detection für mail-test.ch
    host = (request.headers.get("host") or "").lower().split(":")[0]
    if host in ("mail-test.ch", "www.mail-test.ch"):
        return render(request, "mail_test_landing.html",
                       user=None, tenant=None, active=None)

    return render(request, "marketing.html", user=None, tenant=None, active=None)


@router.get("/mail-test")
def mail_test_landing(request: Request):
    """Mail-Tester-fokussierte Landingpage mit SEO-Content. Erreichbar via
    dmarc-geeks.ch/mail-test ODER als / wenn unter mail-test.ch."""
    return render(request, "mail_test_landing.html",
                   user=None, tenant=None, active=None)


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


@router.get("/services/bimi")
def services_bimi(request: Request):
    return render(request, "services/bimi.html", user=None, tenant=None, active=None)


@router.get("/services/healthcare-audit")
def services_healthcare_audit(request: Request):
    """IT-Compliance-Audit fuer Praxen, Psychotherapeut*innen, Zahnaerzte, Kliniken."""
    return render(request, "services/healthcare_audit.html",
                   user=None, tenant=None, active=None)


@router.get("/services/therapie-audit")
def services_therapie_audit(request: Request):
    """IT-Compliance-Audit fuer Naturheilpraxis, Komplementaermedizin, EMR/RME-Therapeut*innen."""
    return render(request, "services/therapie_audit.html",
                   user=None, tenant=None, active=None)


@router.get("/services/finma-audit")
def services_finma_audit(request: Request):
    """FINMA-Compliance-Audit fuer Banken, Versicherungen, Vermoegensverwalter."""
    return render(request, "services/finma_audit.html",
                   user=None, tenant=None, active=None)


@router.get("/partner-werden")
def partner_werden(request: Request):
    """Reseller / Affiliate / Co-managed Landing fuer MSPs, Treuhaender, Agenturen."""
    return render(request, "partner_werden.html", user=None, tenant=None, active=None)


@router.get("/bimi-generator")
def bimi_generator(request: Request, domain: str = ""):
    """Public BIMI-Record-Generator + Live-Check."""
    dom = (domain or "").strip().lower().rstrip(".")
    if dom and "." in dom:
        notify_domain_check(request, tool="bimi-generator", domain=dom)
    return render(request, "bimi_generator.html",
                   user=None, tenant=None, active=None,
                   prefill_domain=dom or "")


@router.get("/api/bimi-check")
def api_bimi_check(request: Request, domain: str):
    """JSON: ist die Domain BIMI-ready? Was fehlt?"""
    from fastapi.responses import JSONResponse
    dom = (domain or "").strip().lower().rstrip(".")
    if not dom or "." not in dom:
        return JSONResponse({"error": "Bitte eine Domain angeben."}, status_code=400)

    # Lead-Signal
    notify_domain_check(request, tool="bimi-generator", domain=dom)

    checks: list[dict] = []
    ready_count = 0
    fail_count = 0

    try:
        import dns.exception, dns.resolver
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = ["1.1.1.1", "8.8.8.8"]
        r.lifetime = 4.0
        r.timeout = 3.0

        # 1) DMARC: muss vorhanden sein UND p=quarantine|reject
        try:
            ans = r.resolve(f"_dmarc.{dom}", "TXT")
            dmarc_text = " ".join("".join(s.decode("utf-8", "replace") for s in rec.strings) for rec in ans).lower()
            if "v=dmarc1" not in dmarc_text:
                checks.append({"key": "dmarc", "label": "DMARC vorhanden",
                                "status": "fail", "detail": "Kein gültiger DMARC-Record."})
                fail_count += 1
            elif "p=quarantine" in dmarc_text or "p=reject" in dmarc_text:
                policy = "reject" if "p=reject" in dmarc_text else "quarantine"
                checks.append({"key": "dmarc", "label": "DMARC mit Enforcement",
                                "status": "pass", "detail": f"p={policy} -- BIMI-Voraussetzung erfuellt"})
                ready_count += 1
            else:
                checks.append({"key": "dmarc", "label": "DMARC mit Enforcement",
                                "status": "fail",
                                "detail": "DMARC vorhanden aber p=none -- BIMI verlangt p=quarantine oder p=reject"})
                fail_count += 1
        except dns.resolver.NXDOMAIN:
            checks.append({"key": "dmarc", "label": "DMARC vorhanden",
                            "status": "fail", "detail": "Kein DMARC-Record auf _dmarc-Subdomain."})
            fail_count += 1
        except (dns.exception.Timeout, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            checks.append({"key": "dmarc", "label": "DMARC-Check",
                            "status": "warn", "detail": "DNS-Timeout — Lookup wiederholen."})

        # 2) BIMI-Record auf default._bimi
        try:
            ans = r.resolve(f"default._bimi.{dom}", "TXT")
            bimi_text = " ".join("".join(s.decode("utf-8", "replace") for s in rec.strings) for rec in ans)
            low = bimi_text.lower()
            if "v=bimi1" in low:
                has_l = "l=" in low
                has_a = "a=" in low
                if has_l:
                    extra = "mit VMC/CMC (a=)" if has_a else "ohne Cert (a=) -- in Gmail kein blauer Tick"
                    status = "pass" if has_a else "warn"
                    checks.append({"key": "bimi", "label": "BIMI-Record",
                                    "status": status, "detail": f"Vorhanden, {extra}"})
                    if has_a: ready_count += 1
                else:
                    checks.append({"key": "bimi", "label": "BIMI-Record",
                                    "status": "fail",
                                    "detail": "Record da, aber kein l= (Logo-URL) -- ungueltig."})
                    fail_count += 1
            else:
                checks.append({"key": "bimi", "label": "BIMI-Record",
                                "status": "fail", "detail": "Kein gueltiger BIMI-Record."})
                fail_count += 1
        except dns.resolver.NXDOMAIN:
            checks.append({"key": "bimi", "label": "BIMI-Record",
                            "status": "fail",
                            "detail": "Kein BIMI-Record gesetzt (auf default._bimi)."})
            fail_count += 1
        except (dns.exception.Timeout, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            checks.append({"key": "bimi", "label": "BIMI-Record",
                            "status": "warn", "detail": "DNS-Lookup nicht eindeutig."})

        # 3) MX vorhanden (sonst macht BIMI wenig Sinn)
        try:
            r.resolve(dom, "MX")
            checks.append({"key": "mx", "label": "MX-Record",
                            "status": "pass", "detail": "Mail-Server fuer diese Domain konfiguriert."})
            ready_count += 1
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            checks.append({"key": "mx", "label": "MX-Record",
                            "status": "warn",
                            "detail": "Kein MX. Domain empfaengt keine Mails -- sendet sie nur?"})

    except Exception as e:  # noqa: BLE001
        checks.append({"key": "general", "label": "DNS-Lookup",
                        "status": "fail", "detail": f"Lookup-Fehler: {e}"})
        fail_count += 1

    return JSONResponse({
        "domain": dom,
        "ready": fail_count == 0 and ready_count >= 2,
        "checks": checks,
    })


@router.get("/wissen")
def wissen(request: Request):
    """Mail-Security-Wissen / Glossar (DMARC, SPF, DKIM erklaert)."""
    return render(request, "wissen.html", user=None, tenant=None, active="wissen")


@router.get("/glossar")
def glossar_alias(request: Request):
    """Alias auf /wissen -- falls jemand alte Links nutzt."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/wissen", status_code=301)


@router.get("/tool")
def tool_landing(request: Request):
    """Produkt-Landing-Page fuer das DMARC-Geeks-Tool selbst."""
    return render(request, "tool_landing.html", user=None, tenant=None, active="tool")


@router.get("/vergleich")
def vergleich(request: Request):
    """DMARC-Tool-Vergleich: DMARC Geeks vs DMARCian vs EasyDMARC vs Valimail.
    SEO-Gold weil viele 'DMARCian alternative' suchen.
    """
    return render(request, "vergleich.html", user=None, tenant=None, active=None)


@router.get("/impressum")
def impressum(request: Request):
    return render(request, "impressum.html", user=None, tenant=None, active=None)


@router.get("/datenschutz")
def datenschutz(request: Request):
    return render(request, "datenschutz.html", user=None, tenant=None, active=None)


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
        # Lead-Signal: jemand prueft eine Domain mit dem DKIM-Inspector
        notify_domain_check(request, tool="dkim-inspector", domain=domain)
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
