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


_COLD_MAIL_TEMPLATE = """Betreff: {subject}

Hallo{name_part},

ich war heute kurz bei {company_part} und habe mir den
Mail-Sicherheits-Status von {domain} angeschaut.

{hook}

Auf der Skala von A bis F steht {domain} aktuell bei {grade} ({score}/100):

{action_lines}

Wenn du Lust hast, schicke ich dir den vollstaendigen 1-Pager-Bericht
(7 Checks, druckbar, kostenlos) - einfach kurz antworten.

Wir machen so etwas regelmaessig fuer Schweizer KMU und MSPs: DMARC-
Einfuehrung ohne Mail-Ausfall, ab CHF 490 als Audit, ab CHF 1990 als
Voll-Migration. Auch als White-Label fuer Agenturen.

Beste Gruesse
Nils Lappenbusch
DMARC Geeks
https://dmarc-geeks.ch
+41 77 950 31 52

--
P.S.: Falls du das schon auf dem Schirm hast, gerne ignorieren -
ich schicke das nicht massenhaft raus, sondern habe gezielt 10-20
Domains aus der Branche angeschaut.
"""


_HOOKS_BY_GRADE = {
    "F": "Kurz gesagt: aktuell kann unter dem Namen {domain} aus dem Internet jeder mailen, ohne dass es als Faelschung erkennbar waere - DMARC und SPF fehlen komplett. Das ist ein Phishing-Risiko, besonders wenn ihr Rechnungen verschickt.",
    "D": "Kurz gesagt: ihr habt nur Basics gesetzt, kein DMARC oder kein DKIM. Damit erreicht ihr bei strengen Empfaengern (Google, Microsoft, Apple Mail) zunehmend den Spam-Ordner statt der Inbox.",
    "C": "Kurz gesagt: Basis ist da, aber DMARC ist noch auf 'beobachten' (p=none) oder Reports werden nicht eingesammelt. Heisst: keiner sieht, wer in eurem Namen mailt.",
    "B": "Kurz gesagt: gut aufgestellt, aber 1-2 Schwaechen lassen sich noch glaetten. Wenn ihr BIMI nutzt, wuerde euer Logo neben jeder Mail im Postfach des Empfaengers stehen - aktuell nicht.",
    "A": "Kurz gesagt: solide Aufstellung. Falls ihr trotzdem mal eine zweite Meinung wollt - oder BIMI/VMC fuer's Logo-neben-Mail-Branding - kein Stress, melde dich gerne.",
}


def render_cold_mail(domain: str, score: dict, *, first_name: str = "",
                     company: str = "", email: str = "") -> str:
    """Personalisiertes Cold-Mail-Template basierend auf Grade-Hook."""
    grade = score.get("grade", "F")
    total = score.get("total", 0)
    actions = score.get("actions", [])
    hook = _HOOKS_BY_GRADE.get(grade, _HOOKS_BY_GRADE["F"]).format(domain=domain)
    action_lines = "\n".join(f"  - {a}" for a in actions[:3]) if actions else "  (keine kritischen Punkte)"
    subject = f"Kurzer Mail-Sicherheits-Check fuer {domain}: Grade {grade}"
    name_part = f" {first_name}" if first_name else ""
    company_part = company or f"`{domain}`"
    return _COLD_MAIL_TEMPLATE.format(
        subject=subject, domain=domain, name_part=name_part,
        company_part=company_part, hook=hook, grade=grade,
        score=total, action_lines=action_lines,
    )
