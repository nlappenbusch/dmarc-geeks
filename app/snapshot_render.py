"""Renderfunktionen fuer Domain-Health-Snapshots — gemeinsam genutzt von:
- scripts/snapshot_batch.py (CLI)
- app/routers/admin_leads.py (Web-UI Batch-Tool)

Keine HTTP- oder DB-Abhaengigkeiten -- pure Funktionen die ein
domain + check-result + score-dict reinkriegen und HTML/Text raus.
"""
from __future__ import annotations

from datetime import datetime, timezone


# Inline-Logo (DMARC Geeks Brille+Envelope, blau-violetter Gradient).
# Wird in standalone-HTML-Snapshots eingebettet damit sie ohne Internet-Zugriff
# komplett darstellbar sind (kein <img src="/static/logo.svg"> noetig).
_LOGO_SVG = """<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="DMARC Geeks" width="34" height="34"><defs><linearGradient id="dgGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#2563eb"/><stop offset="100%" stop-color="#7c3aed"/></linearGradient></defs><rect width="40" height="40" rx="9" fill="url(#dgGrad)"/><path d="M10 17 L10 28 Q10 30 12 30 L28 30 Q30 30 30 28 L30 17 L20 23 Z" fill="#fff"/><circle cx="15" cy="13" r="3" fill="none" stroke="#fff" stroke-width="1.6"/><circle cx="25" cy="13" r="3" fill="none" stroke="#fff" stroke-width="1.6"/><line x1="18" y1="13" x2="22" y2="13" stroke="#fff" stroke-width="1.6"/></svg>"""


def grade_color(grade: str) -> str:
    return {
        "A": "#16a34a", "B": "#65a30d",
        "C": "#d97706", "D": "#dc2626", "F": "#991b1b",
    }.get(grade, "#6b7280")


def normalize_domain(raw: str) -> str:
    d = (raw or "").strip().lower().rstrip(".")
    for prefix in ("http://", "https://", "www."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    if "/" in d:
        d = d.split("/", 1)[0]
    if ":" in d:
        d = d.split(":", 1)[0]
    return d


def render_snapshot_html(domain: str, result: dict, score: dict) -> str:
    """Standalone HTML-Snapshot (kein Template-Engine, eigenstaendig druckbar).

    Kann direkt im Browser geoeffnet, gespeichert, oder per Mail verschickt werden.
    Print-CSS sorgt fuer sauberen A4-Druck (Strg+P).
    """
    grade = score.get("grade", "?")
    grade_label = score.get("grade_label", "")
    total = score.get("total", 0)
    checks = score.get("checks", {})
    actions = score.get("actions", [])
    color = grade_color(grade)
    ts = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    def _detail(name: str) -> str:
        c = checks.get(name) or {}
        status = c.get("status", "info")
        label = c.get("label", "—")
        cls = {"ok": "s-ok", "warn": "s-warn", "fail": "s-fail", "info": "s-info"}[status]
        status_label = {"ok": "OK", "warn": "WARN", "fail": "FEHLT", "info": "INFO"}[status]
        return f"""
          <div class="check {cls}">
            <div class="check-h">{name.upper().replace('_', '-')}</div>
            <div class="check-status">{status_label}</div>
            <div class="check-label">{label}</div>
          </div>"""

    action_html = (
        "".join(f"<li>{a}</li>" for a in actions[:5])
        if actions else "<li>Keine kritischen Punkte gefunden. 🎉</li>"
    )

    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>Mail-Sicherheits-Snapshot: {domain}</title>
<style>
  :root {{ --brand:#2563eb; --text:#0f172a; --muted:#64748b; --border:#e5e7eb;
           --ok:#16a34a; --warn:#d97706; --bad:#dc2626; --grade:{color}; }}
  *{{box-sizing:border-box}}body{{font-family:-apple-system,Inter,sans-serif;color:var(--text);margin:0;padding:32px 24px;line-height:1.55;background:#f3f4f6}}
  .page{{max-width:760px;margin:0 auto;background:white;padding:42px 48px;border-radius:6px;box-shadow:0 4px 24px rgba(0,0,0,0.08)}}
  .head{{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:18px;border-bottom:3px solid var(--brand);margin-bottom:24px}}
  .brand{{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;letter-spacing:-0.02em}} .brand-name span{{color:var(--brand)}}
  .meta{{text-align:right;font-size:11px;color:var(--muted);line-height:1.6}}
  h1{{margin:0 0 4px 0;font-size:26px;letter-spacing:-0.025em;line-height:1.15}} h1 code{{font-family:inherit;color:var(--brand)}}
  .score-row{{display:grid;grid-template-columns:auto 1fr;gap:24px;align-items:center;padding:22px;border-radius:12px;color:white;background:var(--grade);margin:18px 0 26px 0}}
  .grade{{font-size:60px;font-weight:900;line-height:1;letter-spacing:-0.04em}}
  .grade-label{{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;opacity:.85}}
  .grade-headline{{font-size:18px;font-weight:800;margin:2px 0 8px 0}}
  ul.actions{{margin:0;padding-left:18px;font-size:13.5px;line-height:1.6}} ul.actions li{{margin-bottom:4px}}
  h2{{font-size:15px;margin:26px 0 12px 0;padding-bottom:6px;border-bottom:1px solid var(--border)}}
  .check{{padding:12px 14px;border-radius:8px;background:#fafbfd;border-left:3px solid var(--border);margin-bottom:8px;display:grid;grid-template-columns:auto auto 1fr;gap:14px;align-items:center}}
  .check.s-ok{{border-left-color:var(--ok)}} .check.s-warn{{border-left-color:var(--warn)}}
  .check.s-fail{{border-left-color:var(--bad)}} .check.s-info{{border-left-color:var(--brand);opacity:.95}}
  .check-h{{font-weight:700;font-size:13px;letter-spacing:.04em}}
  .check-status{{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:999px;text-transform:uppercase}}
  .s-ok .check-status{{background:rgba(22,163,74,.13);color:var(--ok)}}
  .s-warn .check-status{{background:rgba(217,119,6,.13);color:var(--warn)}}
  .s-fail .check-status{{background:rgba(220,38,38,.13);color:var(--bad)}}
  .s-info .check-status{{background:#f1f5f9;color:var(--muted)}}
  .check-label{{font-size:12.5px;color:var(--text)}}
  .foot{{margin-top:32px;padding-top:14px;border-top:1px solid var(--border);display:flex;justify-content:space-between;font-size:10.5px;color:var(--muted)}}
  @media print{{body{{background:white;padding:0}}.page{{box-shadow:none;border-radius:0;padding:0;max-width:none}}}}
</style></head><body>
<div class="page">
  <div class="head">
    <div class="brand">{_LOGO_SVG}<span class="brand-name">DMARC<span>Geeks</span></span></div>
    <div class="meta"><strong>Mail-Sicherheits-Snapshot</strong>Erstellt: {ts}<br>dmarc-geeks.ch</div>
  </div>
  <h1>Domain: <code>{domain}</code></h1>
  <div style="color:var(--muted);font-size:13px;margin:0 0 12px 0">DNS-basierter Mail-Security-Check &middot; 7 Checks</div>

  <div class="score-row">
    <div>
      <div class="grade">{grade}</div>
      <div style="font-size:12px;opacity:.85;text-align:center">{total}/100</div>
    </div>
    <div>
      <div class="grade-label">Resultat</div>
      <div class="grade-headline">{grade_label}</div>
      <ul class="actions">{action_html}</ul>
    </div>
  </div>

  <h2>Einzelne Checks</h2>
  {_detail("dmarc")}{_detail("spf")}{_detail("dkim")}{_detail("mx")}
  {_detail("mta_sts")}{_detail("tls_rpt")}{_detail("bimi")}

  <div class="foot">
    <span>Erstellt von dmarc-geeks.ch · Mail-Security-Audit · Schweiz</span>
    <span>Kontakt: <a href="https://dmarc-geeks.ch/kontakt">dmarc-geeks.ch/kontakt</a></span>
  </div>
</div></body></html>"""


# Plain-Text-Version (Fallback fuer Reply-Threads). Mit echten Umlauten.
_COLD_MAIL_TEMPLATE = """Betreff: {subject}

Hallo{name_part},

ich habe mir heute kurz die Mail-Sicherheit von {domain} angeschaut – das mache ich für Schweizer KMU regelmäßig, wenn ich auf eine Firma stoße, deren Setup ich nicht kenne.

{hook}

Aktueller Stand auf der Skala A bis F:
{grade} ({score}/100)

Was zuerst angehen:
{action_lines}

Falls du den vollständigen 1-Pager-Bericht (PDF, 7 Checks im Detail) haben möchtest – einfach kurz auf diese Mail antworten, dann schicke ich ihn dir per E-Mail.

Wir bauen sowas regelmäßig für Schweizer KMU und MSPs: DMARC-Einführung ohne Mail-Ausfall, ab CHF 490 als Audit, ab CHF 1990 als Voll-Migration. Auch als White-Label für Agenturen.

Liebe Grüsse aus dem Zürcher Unterland
Nils Lappenbusch

DMARC Geeks · https://dmarc-geeks.ch
+41 77 950 31 52 · nils@dmarc-geeks.ch

--
P.S.: Falls ihr das schon auf dem Schirm habt – gerne ignorieren. Ich schreibe nicht massenhaft, sondern habe gezielt 10–20 Domains aus eurer Branche angeschaut.
"""


# Hooks pro Grade — mit echten Umlauten, persoenlicher Ton.
_HOOKS_BY_GRADE = {
    "F": "Kurz gesagt: aktuell kann unter dem Namen <strong>{domain}</strong> aus dem Internet jeder eine E-Mail verschicken, ohne dass es als Fälschung erkennbar wäre — DMARC und SPF fehlen komplett. Das ist ein konkretes Phishing-Risiko, besonders wenn ihr Rechnungen, Mahnungen oder Lohnabrechnungen verschickt.",
    "D": "Kurz gesagt: bei <strong>{domain}</strong> sind nur die Basics gesetzt — kein DMARC oder kein DKIM. Damit landet ihr bei strengen Empfängern (Google, Microsoft, Apple Mail) zunehmend im Spam-Ordner statt in der Inbox.",
    "C": "Kurz gesagt: die Basis bei <strong>{domain}</strong> ist da, aber DMARC läuft noch auf „beobachten“ (p=none) oder Reports werden nicht eingesammelt. Heißt konkret: niemand bei euch sieht, wer eigentlich in eurem Namen mailt.",
    "B": "Kurz gesagt: <strong>{domain}</strong> ist gut aufgestellt, aber 1–2 Schwächen lassen sich noch glätten. Falls ihr BIMI nutzt, würde euer Logo bei jeder Mail im Posteingang sichtbar sein — aktuell nicht.",
    "A": "Kurz gesagt: solide Aufstellung bei <strong>{domain}</strong>. Falls ihr trotzdem mal eine zweite Meinung wollt — oder BIMI/VMC fürs Logo-neben-Mail-Branding — kein Stress, meldet euch gerne.",
}


def _hook_for(grade: str, domain: str, *, plain: bool = False) -> str:
    raw = _HOOKS_BY_GRADE.get(grade, _HOOKS_BY_GRADE["F"]).format(domain=domain)
    if plain:
        # <strong>…</strong> rauswerfen fuer Plain-Text-Version
        return raw.replace("<strong>", "").replace("</strong>", "").replace("&bdquo;", "„").replace("&ldquo;", '"')
    return raw


def render_cold_mail(domain: str, score: dict, *, first_name: str = "",
                     company: str = "", email: str = "") -> str:
    """Plain-Text-Version (fuer Reply-Threads und Notepad-Copy). Echte Umlaute."""
    grade = score.get("grade", "F")
    total = score.get("total", 0)
    actions = score.get("actions", [])
    hook = _hook_for(grade, domain, plain=True)
    action_lines = "\n".join(f"  • {a}" for a in actions[:3]) if actions else "  (keine kritischen Punkte)"
    subject = f"Kurzer Mail-Sicherheits-Check für {domain} — Grade {grade}"
    name_part = f" {first_name}" if first_name else ""
    return _COLD_MAIL_TEMPLATE.format(
        subject=subject, domain=domain, name_part=name_part,
        hook=hook, grade=grade,
        score=total, action_lines=action_lines,
    )


def render_cold_mail_html(domain: str, score: dict, *, first_name: str = "",
                          company: str = "", email: str = "") -> dict:
    """Fancy HTML-Version fuer Outlook-Copy-Paste. Gibt dict mit subject + html + plain.

    Inline-CSS damit es in Mail-Clients sauber rendert (Outlook, Apple Mail,
    Gmail-Web). Logo als inline SVG. Score-Badge mit Grade-Farbverlauf.

    Sieht aus wie eine persoenliche Nachricht — KEINE Newsletter-/Template-
    Optik, sondern wie eine eilig aber sauber geschriebene Hand-Mail.
    """
    grade = score.get("grade", "F")
    total = score.get("total", 0)
    actions = score.get("actions", [])
    hook = _hook_for(grade, domain, plain=False)
    color = grade_color(grade)
    subject = f"Kurzer Mail-Sicherheits-Check für {domain} — Grade {grade}"
    greeting = f"Hallo {first_name},".strip() if first_name else "Hallo zusammen,"

    actions_html = ""
    if actions:
        for a in actions[:3]:
            actions_html += (
                f'<li style="margin-bottom:6px;color:#1f2937;">{a}</li>'
            )
    else:
        actions_html = '<li style="color:#16a34a;">(keine kritischen Punkte — solide Aufstellung)</li>'

    # Score-Badge inline (Outlook-vertraeglich: kein flex, Tabellen+nbsp)
    score_badge = (
        f'<table cellpadding="0" cellspacing="0" border="0" style="display:inline-table;">'
        f'<tr><td style="background:{color};color:white;border-radius:10px;padding:14px 22px;'
        f'text-align:center;font-family:-apple-system,Inter,sans-serif;line-height:1;">'
        f'<div style="font-size:36px;font-weight:900;letter-spacing:-0.04em;">{grade}</div>'
        f'<div style="font-size:11px;font-weight:600;opacity:.9;margin-top:4px;">{total}/100</div>'
        f'</td></tr></table>'
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,'Segoe UI',Inter,sans-serif;color:#1f2937;background:#ffffff;font-size:14.5px;line-height:1.6;">
<div style="max-width:620px;margin:0 auto;padding:16px 4px;">

  <p style="margin:0 0 14px 0;">{greeting}</p>

  <p style="margin:0 0 14px 0;">ich habe mir heute kurz die Mail-Sicherheit von <strong>{domain}</strong> angeschaut — das mache ich für Schweizer KMU regelmäßig, wenn ich auf eine Firma stoße, deren Setup ich nicht kenne.</p>

  <p style="margin:0 0 18px 0;">{hook}</p>

  <table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 20px 0;border-collapse:separate;">
    <tr>
      <td valign="middle" style="padding-right:18px;">{score_badge}</td>
      <td valign="middle" style="font-size:13.5px;color:#475569;line-height:1.55;">
        Mail-Sicherheits-Grade<br>
        <strong style="font-size:15.5px;color:#1f2937;">{domain}</strong><br>
        <span style="color:#94a3b8;font-size:12px;">DMARC · SPF · DKIM · MX · BIMI</span>
      </td>
    </tr>
  </table>

  <p style="margin:0 0 8px 0;font-weight:600;">Was ich konkret zuerst angehen würde:</p>
  <ol style="margin:0 0 20px 22px;padding:0;">
    {actions_html}
  </ol>

  <p style="margin:0 0 14px 0;">Falls du den <strong>vollständigen 1-Pager-Bericht</strong> haben möchtest (PDF, 7 Checks im Detail, druckbar fürs Compliance-Meeting) — einfach kurz auf diese Mail antworten, dann schicke ich ihn dir per E-Mail.</p>

  <p style="margin:0 0 18px 0;color:#475569;font-size:13.5px;">Wir bauen sowas regelmäßig für Schweizer KMU und MSPs: DMARC-Einführung ohne Mail-Ausfall, ab <strong>CHF 490</strong> als Audit, ab <strong>CHF 1990</strong> als Voll-Migration. Auch als White-Label für Agenturen.</p>

  <p style="margin:0 0 4px 0;">Liebe Grüsse aus dem Zürcher Unterland</p>
  <p style="margin:0 0 18px 0;font-weight:600;">Nils Lappenbusch</p>

  <table cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #e2e8f0;padding-top:14px;margin-top:6px;">
    <tr>
      <td valign="middle" style="padding-right:14px;">
        <svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="DMARC Geeks" width="42" height="42">
          <defs><linearGradient id="dgCm" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#2563eb"/><stop offset="100%" stop-color="#7c3aed"/></linearGradient></defs>
          <rect width="40" height="40" rx="9" fill="url(#dgCm)"/>
          <path d="M10 17 L10 28 Q10 30 12 30 L28 30 Q30 30 30 28 L30 17 L20 23 Z" fill="#fff"/>
          <circle cx="15" cy="13" r="3" fill="none" stroke="#fff" stroke-width="1.6"/>
          <circle cx="25" cy="13" r="3" fill="none" stroke="#fff" stroke-width="1.6"/>
          <line x1="18" y1="13" x2="22" y2="13" stroke="#fff" stroke-width="1.6"/>
        </svg>
      </td>
      <td valign="middle" style="font-size:13px;line-height:1.55;color:#475569;">
        <strong style="color:#1f2937;font-size:14px;">DMARC Geeks</strong> · Mail-Security &amp; Deliverability für KMU<br>
        🌐 <a href="https://dmarc-geeks.ch" style="color:#2563eb;text-decoration:none;">dmarc-geeks.ch</a>
        &nbsp;·&nbsp; 📞 <a href="tel:+41779503152" style="color:#2563eb;text-decoration:none;">+41 77 950 31 52</a>
        &nbsp;·&nbsp; ✉ <a href="mailto:nils@dmarc-geeks.ch" style="color:#2563eb;text-decoration:none;">nils@dmarc-geeks.ch</a>
      </td>
    </tr>
  </table>

  <p style="margin:18px 0 0 0;font-size:12px;color:#94a3b8;line-height:1.55;">
    P.S.: Falls ihr das schon auf dem Schirm habt — gerne ignorieren. Ich schreibe nicht massenhaft, sondern habe gezielt 10–20 Domains aus eurer Branche angeschaut.
  </p>

</div>
</body></html>"""

    # Plain-Version (fuer Mail-Clients ohne HTML-Support oder Copy-as-plain)
    plain = render_cold_mail(domain, score, first_name=first_name,
                              company=company, email=email)

    return {
        "subject": subject,
        "html": html,
        "plain": plain,
    }
