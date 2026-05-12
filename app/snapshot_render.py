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
# Das Thema ist zweigleisig: Mail-SICHERHEIT (Phishing-Schutz) UND
# Mail-ZUSTELLBARKEIT (eure Mails landen in der Inbox, nicht im Spam).
# Beides hängt an den gleichen DNS-Records (SPF / DKIM / DMARC).
_COLD_MAIL_TEMPLATE = """Betreff: {subject}

Hallo{name_part},

ich habe mir heute kurz die Mail-Sicherheit UND Zustellbarkeit von {domain} angeschaut – beides hängt an den gleichen DNS-Records (SPF/DKIM/DMARC), und ich mache das regelmässig für Schweizer KMU.

{hook}

Konkret betrifft das zwei Sachen gleichzeitig:
  1. SICHERHEIT: kann jemand in eurem Namen schreiben? (Phishing-Risiko)
  2. ZUSTELLBARKEIT: kommen EURE Mails bei Kunden, Patienten, Lieferanten an?
     (Spam-Ordner-Problem — typisch ~5-30% Mailverlust bei kaputtem Setup)

Aktueller Stand auf der Skala A bis F:
{grade} ({score}/100)

Was zuerst angehen:
{action_lines}

Falls du den vollständigen 1-Pager-Bericht (PDF, 7 Checks im Detail) haben möchtest – einfach kurz auf diese Mail antworten, dann schicke ich ihn dir per E-Mail.

Wir bauen sowas regelmässig für Schweizer KMU und MSPs: DMARC-Einführung ohne Mail-Ausfall, ab CHF 490 als Audit, ab CHF 1990 als Voll-Migration. Auch als White-Label für Agenturen.

Liebe Grüsse aus dem Zürcher Unterland
Nils Lappenbusch
DMARC Geeks · https://dmarc-geeks.ch
+41 77 950 31 52 · nils@dmarc-geeks.ch

--
P.S.: Falls ihr das schon auf dem Schirm habt – gerne ignorieren. Ich schreibe nicht massenhaft, sondern habe gezielt 10–20 Domains aus eurer Branche angeschaut.
"""


# Hooks pro Grade — beide Angles ansprechen: SICHERHEIT + ZUSTELLBARKEIT.
# Werden mit Context-Add-Ons angereichert (rua, SPF-Lookups) wenn der
# DNS-Check entsprechende Daten liefert.
_HOOKS_BY_GRADE = {
    "F": "Kurz gesagt: aktuell kann unter dem Namen <strong>{domain}</strong> aus dem Internet jeder eine E-Mail verschicken, ohne dass es als Fälschung erkennbar wäre — DMARC und SPF fehlen komplett. Und umgekehrt: <strong>eure eigenen Mails</strong> (Terminbestätigungen, Rechnungen, Mahnungen, …) landen bei Gmail/Outlook/Apple Mail zunehmend im Spam-Ordner, weil eure Domain für die nicht als „authentifizierter Absender“ erkennbar ist.",
    "D": "Kurz gesagt: bei <strong>{domain}</strong> sind nur die Basics gesetzt — kein DMARC oder kein DKIM. Praktisch heisst das: eure eigenen Mails landen bei strengen Empfängern (Google, Microsoft, Apple Mail) zunehmend im Spam-Ordner statt in der Inbox. Typisch <strong>5-30% Zustellrate-Verlust</strong> — also Rechnungen, Termin-Bestätigungen, Newsletter die nie ankommen. Gleichzeitig ist Spoofing in eurem Namen problemlos möglich.",
    "C": "Kurz gesagt: die Basis bei <strong>{domain}</strong> ist da, aber DMARC läuft noch auf „beobachten“ (p=none){rua_sniplet}. Heisst konkret: <strong>niemand bei euch sieht</strong>, wer in eurem Namen mailt und ob eure eigenen Mails sauber zugestellt werden. Die scharfe Policy (<code>p=quarantine</code> / <code>p=reject</code>) ist der eigentliche Schutz — ohne Reports kann man die aber nicht datengetrieben einführen.",
    "B": "Kurz gesagt: <strong>{domain}</strong> ist gut aufgestellt, aber 1–2 Schwächen lassen sich noch glätten — und meist hängen die direkt an der Zustellbarkeit (z.B. SPF-Lookup-Count grenzwertig). Falls ihr BIMI nutzt, würde euer Logo bei jeder Mail im Posteingang sichtbar sein, was die Öffnungsrate spürbar hebt — aktuell nicht.",
    "A": "Kurz gesagt: solide Aufstellung bei <strong>{domain}</strong> — sowohl bei Sicherheit als auch bei Zustellbarkeit. Falls ihr trotzdem mal eine zweite Meinung wollt, oder BIMI/VMC fürs Logo-neben-Mail-Branding (Öffnungsraten-Boost) — kein Stress, meldet euch gerne.",
}


def _build_context_extras(check_result: dict | None) -> list[str]:
    """Konkrete Beobachtungen aus dem DNS-Check, die im Cold-Mail-Body als
    Bullet-Punkte erscheinen (zusaetzlich zu den generischen actions aus
    score_check). Macht die Mail glaubwuerdig: 'er hat wirklich geschaut'.

    Returns Liste von HTML-faehigen Strings.
    """
    extras: list[str] = []
    if not check_result:
        return extras

    spf = check_result.get("spf") or {}
    dmarc = check_result.get("dmarc") or {}
    dkim_list = check_result.get("dkim") or []

    # SPF-Redirect-Override: redirect= ignoriert alle anderen Mechanismen
    if spf.get("redirect_overrides") and spf.get("redirect_target"):
        extras.append(
            f"<strong>SPF wird komplett von <code>{spf['redirect_target']}</code> "
            "überschrieben</strong> — euer eigener Record enthält zwar "
            "<code>ip4:</code>/<code>include:</code>-Einträge, aber durch das "
            "<code>redirect=</code> werden die <em>alle</em> ignoriert (RFC 7208 §6.1). "
            "Heisst: was ihr da geschrieben habt, wirkt nicht — die andere Domain "
            "bestimmt komplett wer in eurem Namen senden darf."
        )

    # SPF-Lookup-Count Detail
    lc = spf.get("lookup_count")
    if lc is not None and spf.get("present"):
        if lc > 10:
            extras.append(
                f"<strong>SPF-Lookup-Limit überschritten</strong> ({lc} > 10) — "
                "der Record wird von Microsoft/Google komplett ignoriert, eure "
                "Mails laufen aktuell <em>ohne</em> SPF-Schutz."
            )
        elif lc >= 8:
            extras.append(
                f"<strong>SPF-Lookup-Count grenzwertig</strong> ({lc}/10) — "
                "ein weiterer include reicht und SPF kippt. Konsolidierung "
                "wäre fällig (z.B. via SPF-Flattening)."
            )

    # DMARC-Report-Empfänger
    if dmarc.get("present"):
        rua = dmarc.get("rua") or []
        policy = (dmarc.get("policy") or "none").lower()
        if not rua:
            extras.append(
                "<strong>Kein DMARC-Report-Empfänger</strong> (kein <code>rua=</code> "
                "im Record) — ihr seht aktuell <em>nicht</em>, wer in eurem Namen "
                "mailt. Ohne Reports lässt sich auch <code>p=quarantine/reject</code> "
                "nicht datengetrieben einführen."
            )
        elif policy == "none":
            who = rua[0] if rua else "?"
            extras.append(
                f"Reports gehen an <code>{who}</code>, aber Policy steht noch auf "
                "<code>p=none</code> — d.h. ihr seht zwar wer mailt, blockiert aber "
                "noch nichts. Typisch 2-4 Wochen Reports auswerten, dann auf "
                "<code>p=quarantine</code> wechseln."
            )

    # DKIM-Selektor-Schwaeche
    if not dkim_list and (check_result.get("mx") or {}).get("present"):
        extras.append(
            "<strong>Kein DKIM-Selektor gefunden.</strong> Entweder ist DKIM nicht "
            "konfiguriert, oder der Selektor heisst exotisch — beides hab ich "
            "in 10 Minuten geklärt."
        )

    return extras


# ============================================================================
# Branchen-Detection + Branchen-spezifische CTAs
# ============================================================================
# Aus (domain, company_name) heuristisch die Branche ableiten und in der
# Cold-Mail einen anderen Schlussabsatz / CTA setzen.

_INDUSTRY_KEYWORDS = {
    "it": [
        "it-", "-it.", "informatik", "systems", "tech", "cloud", "hosting",
        "soft", "digital", "consult", "msp", "iaas", "saas",
        "netzwerk", "support", "service", "sysadm", "computer",
    ],
    # Schulmedizin / klassische Gesundheit
    "healthcare": [
        "zahnarzt", "dentist", "dental", "kfo", "klinik", "spital",
        "medi-", "medic", "doc-", "doctor", "arzt", "ärzte",
        "aerzte", "hausarzt", "kinderarzt", "internist", "orthopaed",
        "chiropract", "ergotherap", "logopaed", "tierarzt",
        "physio",  # physio meist mit FMH-Anbindung
    ],
    # Psychotherapeut·innen mit PsyG-Bewilligung (FSP/ASP/SBAP/SVNP).
    # Eigene Kategorie weil deren IT-Bedarf umfassender ist (Anordnungsmodell,
    # Tarpsy, Berufsgeheimnis StGB 321). Hat Vorrang vor "therapie" weil
    # spezifischer.
    "psychotherapie": [
        "psychotherap", "psychotherapie", "psychologin", "psychologe",
        "psycholog", "psychiat",
        "tiefenpsycholog", "verhaltensther", "kvt", "systemisch",
        "ifs", "schematherap", "tfp",
        "fsp-", "asp-", "sbap-", "svnp-",
        "klinpsy", "kinderpsy", "jugendpsy",
    ],
    # Komplementärmedizin / Naturheilkunde / EMR/RME-Therapeut·innen.
    # WICHTIG: Reihenfolge nach healthcare und psychotherapie — wenn jemand
    # 'praxis-zahnarzt-x.ch' hat, soll healthcare zuerst greifen.
    # 'praxis' alleine ist hier raus (zu generisch) — sonst landen klassische
    # Arzt-Praxen falsch in therapie. Dafuer haben wir 'heilpraxis'.
    "therapie": [
        "naturheil", "heilpraktiker", "heilpraxis", "alternativ",
        "komplementaer", "komplementär", "komplmed",
        "tcm", "ayurv", "homoeop", "homöop", "phytother",
        "osteopath", "kinesio", "shiatsu", "akupunktur", "akupressur",
        "craniosacral", "feldenkrais", "polarity", "reflexzonen",
        "atemtherap", "energetisch", "reiki", "bach-bluet", "bachblut",
        "hypno", "mbsr", "mindful", "achtsam", "yoga",
        "coaching", "coach.", "geist", "seele",
    ],
    "finma": [
        "bank", "kantonalbank", "raiffeisen", "treuhand", "fiduciary",
        "versicher", "insurance", "broker", "rueckver", "ckversich",
        "wealth", "asset", "vermögens", "vermoegens", "finanz", "fund",
        "advisor", "vermögensver", "vermoegensver", "investment",
        "kapitalanlage",
    ],
}


def _detect_industry(domain: str, company_name: str = "") -> Optional[str]:
    """Heuristik: aus domain + company_name die Branche ableiten.
    Returns 'it' | 'healthcare' | 'finma' | None."""
    haystack = f"{domain or ''} {company_name or ''}".lower()
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in haystack:
                return industry
    return None


# Branchen-spezifische CTA-Blöcke (HTML). Werden VOR der Standard-Signatur
# eingefügt. Stil: kleine Card mit Branchen-spezifischem Pitch.
def _industry_cta_html(industry: str, brand_color: str = "#2563eb") -> str:
    if industry == "it":
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;'
            'margin:14px 0 18px 0;border-collapse:separate;background:linear-gradient'
            '(135deg, rgba(37,99,235,.05), rgba(124,58,237,.05));border:1px solid rgba(37,99,235,.25);'
            'border-radius:12px;"><tr><td style="padding:18px 22px;">'
            '<div style="font-weight:700;font-size:14px;color:#1f2937;margin-bottom:6px;">'
            '🛠 Du bist IT-Dienstleister? Verdiene mit unserem Service mit.</div>'
            '<div style="color:#475569;font-size:13.5px;line-height:1.6;">'
            'Unser <strong>Multi-Tenant DMARC-Analyzer</strong> verwaltet das DMARC-Setup '
            'deiner Endkunden zentral — eigene Subdomain, dein Branding, deine Mandantenverwaltung. '
            'Du kassierst Marge, wir liefern Tech + 2nd-Level-Support. '
            '<strong>Reseller-Pakete ab CHF 199/Mo</strong> für 10 Tenants.<br><br>'
            f'<a href="https://dmarc-geeks.ch/partner-werden" style="color:{brand_color};'
            'text-decoration:none;font-weight:600;">→ Partnerprogramm ansehen</a> &nbsp;·&nbsp; '
            f'<a href="https://dmarc-geeks.ch/tool" style="color:{brand_color};'
            'text-decoration:none;font-weight:600;">→ Tool im Detail</a>'
            '</div></td></tr></table>'
        )
    elif industry == "healthcare":
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;'
            'margin:14px 0 18px 0;border-collapse:separate;background:linear-gradient'
            '(135deg, rgba(22,163,74,.05), rgba(13,148,136,.05));border:1px solid rgba(22,163,74,.25);'
            'border-radius:12px;"><tr><td style="padding:18px 22px;">'
            '<div style="font-weight:700;font-size:14px;color:#1f2937;margin-bottom:6px;">'
            '⚕️ Healthcare-Sonderfall: HIN-Anschluss + DSG-Patientendaten</div>'
            '<div style="color:#475569;font-size:13.5px;line-height:1.6;">'
            'Praxen, Kliniken und Therapeut*innen haben besondere Anforderungen: '
            '<strong>HIN-Anschluss</strong> für FHIR/HL7-Austausch, DSG-Konformität bei '
            'Patientendaten, und je nach Verband (FMH/SSO/mfe) konkrete IT-Sicherheits-'
            'Vorgaben. Wir machen <strong>Mail-Infrastruktur + M365-Tenant-Audits</strong> '
            'für Healthcare ab CHF 690 — inkl. HIN-Anbindung wenn nötig.<br><br>'
            f'<a href="https://dmarc-geeks.ch/services/healthcare-audit" style="color:#0d9488;'
            'text-decoration:none;font-weight:600;">→ Healthcare-IT-Audit ansehen</a> &nbsp;·&nbsp; '
            f'<a href="https://dmarc-geeks.ch/services/hin" style="color:#0d9488;'
            'text-decoration:none;font-weight:600;">→ HIN-Service</a>'
            '</div></td></tr></table>'
        )
    elif industry == "psychotherapie":
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;'
            'margin:14px 0 18px 0;border-collapse:separate;background:linear-gradient'
            '(135deg, rgba(124,58,237,.05), rgba(99,102,241,.05));border:1px solid rgba(124,58,237,.3);'
            'border-radius:12px;"><tr><td style="padding:18px 22px;">'
            '<div style="font-weight:700;font-size:14px;color:#1f2937;margin-bottom:6px;">'
            '🧠 Psychotherapie-Spezifikum: PsyG + Anordnungsmodell + Berufsgeheimnis</div>'
            '<div style="color:#475569;font-size:13.5px;line-height:1.6;">'
            'Psychotherapeut·innen mit PsyG-Bewilligung (FSP/ASP/SBAP/SVNP) haben '
            'besondere IT-Anforderungen: <strong>Schweigepflicht nach StGB 321</strong>, '
            '<strong>Anordnungsmodell-Korrespondenz</strong> mit Krankenkassen seit '
            '07/2022, revDSG-Vorgaben für Therapie-Notizen, DSG-konforme Video-Sprech'
            'stunde. Wir machen <strong>komplette IT-Begleitung</strong> für eure Praxis '
            '— Mail, Praxis-Software, Cloud, Video, Dokumentation. Audit ab CHF 690, '
            'Komplett-Setup ab CHF 2490.<br><br>'
            f'<a href="https://dmarc-geeks.ch/services/psychotherapie-it" '
            'style="color:#7c3aed;text-decoration:none;font-weight:600;">→ Psychotherapie-IT ansehen</a>'
            '</div></td></tr></table>'
        )
    elif industry == "therapie":
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;'
            'margin:14px 0 18px 0;border-collapse:separate;background:linear-gradient'
            '(135deg, rgba(132,204,22,.05), rgba(16,185,129,.05));border:1px solid rgba(132,204,22,.3);'
            'border-radius:12px;"><tr><td style="padding:18px 22px;">'
            '<div style="font-weight:700;font-size:14px;color:#1f2937;margin-bottom:6px;">'
            '🌿 Naturheil/Komplementärmedizin: DSG + EMR/RME-tauglich</div>'
            '<div style="color:#475569;font-size:13.5px;line-height:1.6;">'
            'Komplementärtherapeut·innen, Naturheilpraktiker·innen, Osteopath·innen, '
            'TCM-/Akupunktur-Praktizierende: euer Beruf lebt vom Vertrauen. Patienten- '
            'und Krankenkassen-Korrespondenz muss <strong>DSG-konform</strong> laufen, sonst '
            'drohen revDSG-Bussgelder (bis CHF 250\'000) und ASCA/OdA AM-Probleme. '
            'Wir machen einen <strong>spezifischen Mini-Audit</strong> für eure Praxis '
            'ab CHF 590 — inkl. DSG-Dokumentation.<br><br>'
            f'<a href="https://dmarc-geeks.ch/services/therapie-audit" style="color:#65a30d;'
            'text-decoration:none;font-weight:600;">→ KomplMed-Audit ansehen</a> &nbsp;·&nbsp; '
            f'<a href="https://dmarc-geeks.ch/services/dmarc" style="color:#65a30d;'
            'text-decoration:none;font-weight:600;">→ Mail-Setup-Service</a>'
            '</div></td></tr></table>'
        )
    elif industry == "finma":
        return (
            '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;'
            'margin:14px 0 18px 0;border-collapse:separate;background:linear-gradient'
            '(135deg, rgba(220,38,38,.04), rgba(245,158,11,.04));border:1px solid rgba(220,38,38,.2);'
            'border-radius:12px;"><tr><td style="padding:18px 22px;">'
            '<div style="font-weight:700;font-size:14px;color:#1f2937;margin-bottom:6px;">'
            '🏛 FINMA-Aufsicht: Mail-Sicherheit als Compliance-Pflicht</div>'
            '<div style="color:#475569;font-size:13.5px;line-height:1.6;">'
            'FINMA-Rundschreiben 2023/1 + 2018/3 (Operative Risiken / Outsourcing) '
            'fordern <strong>Mail-Authentifizierung</strong> als Teil der ICT-Sicherheit. '
            'Banken, Vermögensverwalter und Versicherungs-Broker müssen DMARC + SPF + DKIM '
            'nachweisen können — bei Audit, Inspection, ISAE 3402. Wir machen den '
            '<strong>FINMA-Compliance-Audit für Mail-Infrastruktur</strong> mit Audit-Brief '
            'für deine Prüfer ab CHF 1490.<br><br>'
            f'<a href="https://dmarc-geeks.ch/services/finma-audit" style="color:#dc2626;'
            'text-decoration:none;font-weight:600;">→ FINMA-Audit ansehen</a> &nbsp;·&nbsp; '
            f'<a href="https://dmarc-geeks.ch/services/dmarc" style="color:#dc2626;'
            'text-decoration:none;font-weight:600;">→ DMARC-Implementation</a>'
            '</div></td></tr></table>'
        )
    return ""


def _industry_cta_plain(industry: str) -> str:
    if industry == "it":
        return (
            "\n\n🛠 Du bist IT-Dienstleister? Verdiene mit:\n"
            "Unser Multi-Tenant DMARC-Analyzer verwaltet das DMARC-Setup deiner Endkunden "
            "zentral — eigene Subdomain, dein Branding. Reseller-Pakete ab CHF 199/Mo.\n"
            "→ https://dmarc-geeks.ch/partner-werden\n"
        )
    elif industry == "healthcare":
        return (
            "\n\n⚕️ Healthcare-Sonderfall: HIN + DSG-Patientendaten\n"
            "Praxen/Kliniken/Therapeut*innen haben besondere Anforderungen (HIN-Anschluss, "
            "DSG, Verband-Vorgaben). Healthcare-IT-Audit ab CHF 690.\n"
            "→ https://dmarc-geeks.ch/services/healthcare-audit\n"
        )
    elif industry == "psychotherapie":
        return (
            "\n\n🧠 Psychotherapie-IT: PsyG + Anordnungsmodell + Berufsgeheimnis\n"
            "Psychotherapeut·innen mit PsyG-Bewilligung haben besondere Anforderungen: "
            "Schweigepflicht nach StGB 321, Anordnungsmodell-Korrespondenz, revDSG für "
            "Therapie-Notizen, DSG-konforme Video-Sprechstunde. Komplett-IT-Beratung "
            "ab CHF 690 (Audit) bis CHF 2490 (Komplett-Setup).\n"
            "→ https://dmarc-geeks.ch/services/psychotherapie-it\n"
        )
    elif industry == "therapie":
        return (
            "\n\n🌿 Komplementärmedizin: DSG + EMR/RME-tauglich\n"
            "Naturheilpraxis/TCM/Osteopathie/Kinesiologie: Patientendaten sind besonders "
            "schützenswert (revDSG Art. 5 lit. c, Bussgelder bis CHF 250'000). "
            "Mini-Audit für Naturheil-Praxen ab CHF 590.\n"
            "→ https://dmarc-geeks.ch/services/therapie-audit\n"
        )
    elif industry == "finma":
        return (
            "\n\n🏛 FINMA-Aufsicht: Mail-Sicherheit als Compliance-Pflicht\n"
            "FINMA-Rundschreiben 2023/1 + 2018/3 fordern Mail-Authentifizierung als Teil "
            "der ICT-Sicherheit. FINMA-Compliance-Audit ab CHF 1490.\n"
            "→ https://dmarc-geeks.ch/services/finma-audit\n"
        )
    return ""


def _hook_for(grade: str, domain: str, check_result: dict | None = None,
              *, plain: bool = False) -> str:
    """Hook mit Context-Anreicherung. Fuer Grade C wird der rua_sniplet
    dynamisch eingesetzt damit man konkret 'oder Reports werden nicht
    eingesammelt' (wenn rua leer) vs 'aber niemand kuckt rein' bekommt.
    """
    template = _HOOKS_BY_GRADE.get(grade, _HOOKS_BY_GRADE["F"])

    rua_sniplet = ""
    if "{rua_sniplet}" in template and check_result:
        dmarc = check_result.get("dmarc") or {}
        if not (dmarc.get("rua") or []):
            rua_sniplet = " und es ist auch keine Report-Adresse gesetzt (kein <code>rua=</code>)"
        else:
            rua_sniplet = ""  # leer = der Satz wird klassich weitergefuehrt
    raw = template.format(domain=domain, rua_sniplet=rua_sniplet)

    if plain:
        # HTML-Tags rauswerfen fuer Plain-Text-Version
        raw = raw.replace("<strong>", "").replace("</strong>", "")
        raw = raw.replace("<em>", "").replace("</em>", "")
        raw = raw.replace("<code>", "").replace("</code>", "")
    return raw


# ============================================================================
# Followup-Mail-Sequenzen
# ============================================================================
# Drei Followup-Templates, jeweils mit anderem Hook:
#   1) "Sanftes Nachhaken" — 3-5 Tage nach Erst-Mail
#   2) "Neuer Aspekt" — 7-14 Tage später, mit anderem Argument
#   3) "Abschluss" — 14-21 Tage später, klares Statement + Loslassen
#
# Wichtig: jede Mail steht für sich, soll nicht den vorherigen Thread spammen.
# User schickt die einfach als neue Mail an die selbe Adresse.

_FOLLOWUP_TEMPLATES = {
    1: {
        "subject": "Nochmal kurz zum Thema {domain}",
        "body": """Hallo{name_part},

ich wollte nochmal kurz nachhaken — vor einer Woche hatte ich dir einen Mail-Sicherheits-Check für {domain} geschickt (Grade {grade}).

Vielleicht ging die Mail unter — kein Stress. Aber falls es bei euch grad sowieso heisser Punkt ist, lass uns 20 Min telefonieren. Ich erkläre kostenlos:

  - Was die Risiken konkret bedeuten (in Geld, nicht in DNS-Jargon)
  - Welche zwei Sachen ihr selbst in einer halben Stunde fixen könnt
  - Wann wir helfen müssten und was das kostet

Ist null Verpflichtung. Antworte einfach mit Wunsch-Slot oder ruf direkt an: +41 77 950 31 52.

Liebe Grüsse
Nils Lappenbusch
DMARC Geeks · https://dmarc-geeks.ch
""",
    },
    2: {
        "subject": "{domain} — vielleicht hilft euch das",
        "body": """Hallo{name_part},

falls ich mit meinen letzten Mails den falschen Moment getroffen habe — kein Problem.

Ich wollte heute aber noch einen Punkt erwähnen den ich öfters höre: viele KMU realisieren erst dann dass ihre Mail-Setup kaputt ist, wenn die ERSTEN Rechnungen im Spam landen oder ein PHISHING-FALL mit dem Firma-Namen passiert.

Ich hab dafür eine ganz konkrete Check-Liste gebaut — 10 Punkte, alle selbst prüfbar in 30 Minuten. Wenn du mir kurz Bescheid gibst, schicke ich dir die PDF.

Plus: hier ein Direkt-Link auf eure aktuelle Diagnose:
  https://dmarc-geeks.ch/check?domain={domain}

Liebe Grüsse
Nils Lappenbusch
+41 77 950 31 52 · nils@dmarc-geeks.ch
""",
    },
    3: {
        "subject": "Letzte Mail von mir zu {domain}",
        "body": """Hallo{name_part},

das ist meine letzte Mail zu dem Thema, versprochen.

Mail-Sicherheit ist nicht jedermanns Priorität — ich versteh's. Wenn ihr es trotzdem irgendwann anpacken wollt, hier ist meine Kontakt-Info nochmal für die Schublade:

  Nils Lappenbusch
  DMARC Geeks
  +41 77 950 31 52
  nils@dmarc-geeks.ch
  https://dmarc-geeks.ch/services/dmarc

Falls du gerade nicht buchen aber meine Cheatsheets im Postfach haben willst:
  https://dmarc-geeks.ch/wissen
  https://dmarc-geeks.ch/blog

Sonst alles Gute mit eurem Setup —

Nils
""",
    },
}


def render_followup_mail(domain: str, sequence_nr: int, *,
                          first_name: str = "", grade: str = "F") -> dict:
    """Followup-Mail Nr. 1, 2 oder 3. Gibt dict {subject, plain} zurück.
    Keine HTML-Version: Followups sind absichtlich plain-text (wirkt persönlicher).
    """
    if sequence_nr not in _FOLLOWUP_TEMPLATES:
        sequence_nr = 1
    tpl = _FOLLOWUP_TEMPLATES[sequence_nr]
    name_part = f" {first_name}" if first_name else ""
    subject = tpl["subject"].format(domain=domain)
    body = tpl["body"].format(domain=domain, name_part=name_part, grade=grade)
    return {"subject": subject, "plain": body, "sequence_nr": sequence_nr}


def render_cold_mail(domain: str, score: dict, *, first_name: str = "",
                     company: str = "", email: str = "",
                     check_result: dict | None = None) -> str:
    """Plain-Text-Version (fuer Reply-Threads und Notepad-Copy). Echte Umlaute."""
    grade = score.get("grade", "F")
    total = score.get("total", 0)
    actions = score.get("actions", [])
    hook = _hook_for(grade, domain, check_result, plain=True)
    action_lines = "\n".join(f"  • {a}" for a in actions[:3]) if actions else "  (keine kritischen Punkte)"

    # Context-Extras als zusaetzliche Bullet-Punkte unter den Actions
    extras_plain = ""
    if check_result:
        extras = _build_context_extras(check_result)
        if extras:
            extras_plain = "\nKonkret bei euch:\n" + "\n".join(
                "  • " + e.replace("<strong>", "").replace("</strong>", "")
                         .replace("<em>", "").replace("</em>", "")
                         .replace("<code>", "").replace("</code>", "")
                for e in extras
            ) + "\n"

    subject = f"Mail-Sicherheit & Zustellbarkeit von {domain} — Grade {grade}"
    name_part = f" {first_name}" if first_name else ""

    # Branchen-spezifischer CTA-Block (Plain-Version)
    industry = _detect_industry(domain, company)
    industry_cta = _industry_cta_plain(industry) if industry else ""

    return _COLD_MAIL_TEMPLATE.format(
        subject=subject, domain=domain, name_part=name_part,
        hook=hook, grade=grade,
        score=total, action_lines=action_lines + extras_plain + industry_cta,
    )


def _render_check_strip_html(check_result: dict, score: dict) -> str:
    """Mini-Snapshot-Card mit den 5 Haupt-Checks als Ampel-Strip — wird in
    der Cold-Mail unter dem Score-Badge eingebettet. Outlook-vertraegliches
    Table-Layout."""
    if not check_result:
        return ""
    checks = score.get("checks", {})
    rows = [("SPF", "spf"), ("DKIM", "dkim"), ("DMARC", "dmarc"),
            ("MX", "mx"), ("BIMI", "bimi")]
    # ok=green, warn=amber, fail=red, info=gray
    color_map = {"ok": "#16a34a", "warn": "#d97706",
                  "fail": "#dc2626", "info": "#94a3b8"}
    icon_map = {"ok": "✓", "warn": "!", "fail": "✗", "info": "·"}
    cells = []
    for label, key in rows:
        c = checks.get(key) or {}
        status = c.get("status", "info")
        col = color_map.get(status, "#94a3b8")
        ic = icon_map.get(status, "·")
        cells.append(
            f'<td align="center" style="padding:6px 8px;font-family:-apple-system,Inter,sans-serif;">'
            f'<div style="width:36px;height:36px;border-radius:50%;background:{col};color:white;'
            f'line-height:36px;font-weight:800;font-size:18px;margin:0 auto 4px;">{ic}</div>'
            f'<div style="font-size:11px;color:#475569;font-weight:600;">{label}</div></td>'
        )
    return (
        '<table cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 0 20px 0;width:100%;border-collapse:collapse;">'
        '<tr>' + "".join(cells) + '</tr></table>'
    )


def render_cold_mail_html(domain: str, score: dict, *, first_name: str = "",
                          company: str = "", email: str = "",
                          check_result: dict | None = None) -> dict:
    """Fancy HTML-Version fuer Outlook-Copy-Paste. Gibt dict mit subject + html + plain.

    Inline-CSS damit es in Mail-Clients sauber rendert (Outlook, Apple Mail,
    Gmail-Web). Logo als inline SVG. Score-Badge mit Grade-Farbverlauf.

    Sieht aus wie eine persoenliche Nachricht — KEINE Newsletter-/Template-
    Optik, sondern wie eine eilig aber sauber geschriebene Hand-Mail.
    """
    grade = score.get("grade", "F")
    total = score.get("total", 0)
    actions = score.get("actions", [])
    hook = _hook_for(grade, domain, check_result, plain=False)
    color = grade_color(grade)
    subject = f"Mail-Sicherheit & Zustellbarkeit von {domain} — Grade {grade}"
    greeting = f"Hallo {first_name},".strip() if first_name else "Hallo zusammen,"

    actions_html = ""
    if actions:
        for a in actions[:3]:
            actions_html += (
                f'<li style="margin-bottom:8px;color:#1f2937;line-height:1.6;">{a}</li>'
            )
    else:
        actions_html = '<li style="color:#16a34a;">(keine kritischen Punkte — solide Aufstellung)</li>'

    # Extras: konkrete Beobachtungen aus dem Check (rua, SPF-Lookups, ...)
    extras = _build_context_extras(check_result) if check_result else []
    extras_html = ""
    if extras:
        extras_items = "".join(
            f'<li style="margin-bottom:10px;color:#1f2937;line-height:1.6;">{e}</li>'
            for e in extras
        )
        extras_html = (
            '<div style="background:#fef3c7;border-left:4px solid #d97706;'
            'padding:14px 18px;border-radius:0 8px 8px 0;margin:0 0 20px 0;">'
            '<div style="font-weight:700;color:#92400e;font-size:13px;'
            'text-transform:uppercase;letter-spacing:0.04em;margin-bottom:8px;">'
            '🔍 Konkret bei euch entdeckt</div>'
            f'<ul style="margin:0;padding-left:20px;">{extras_items}</ul>'
            '</div>'
        )

    # Branchen-Detection + CTA-Block (IT-Dienstleister/Healthcare/FINMA)
    industry = _detect_industry(domain, company)
    industry_cta = _industry_cta_html(industry) if industry else ""

    # Mini-Snapshot-Card (5 Ampeln) — visualisiert was geprueft wurde
    snapshot_strip = _render_check_strip_html(check_result or {}, score)

    # Score-Badge mit Grade-Label
    grade_labels = {"A": "Exzellent", "B": "Gut, mit Feinschliff",
                     "C": "Solide Basis, Lücken", "D": "Riskant",
                     "F": "Akut handlungsbedürftig"}
    grade_label = score.get("grade_label") or grade_labels.get(grade, "")
    score_card = (
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:0 0 8px 0;border-collapse:collapse;'
        f'background:linear-gradient(135deg,{color} 0%,{color}dd 100%);'
        f'border-radius:14px;">'
        f'<tr>'
        f'<td valign="middle" style="padding:22px 26px;color:white;'
        f'font-family:-apple-system,Inter,sans-serif;">'
        f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;opacity:0.85;margin-bottom:4px;">Mail-Sicherheit &amp; Zustellbarkeit</div>'
        f'<div style="font-size:20px;font-weight:700;letter-spacing:-0.02em;margin-bottom:2px;">'
        f'<code style="font-family:inherit;background:rgba(255,255,255,.18);'
        f'padding:2px 10px;border-radius:6px;">{domain}</code></div>'
        f'<div style="font-size:13.5px;opacity:0.9;margin-top:4px;">{grade_label}</div>'
        f'</td>'
        f'<td valign="middle" align="right" style="padding:22px 26px;color:white;'
        f'font-family:-apple-system,Inter,sans-serif;text-align:right;">'
        f'<div style="font-size:64px;font-weight:900;line-height:1;letter-spacing:-0.05em;">{grade}</div>'
        f'<div style="font-size:13px;font-weight:600;opacity:0.85;margin-top:6px;">{total}/100</div>'
        f'</td>'
        f'</tr></table>'
    )

    # Snapshot-CTA-Box (auffaelliger Button + Link zum 1-Pager)
    snapshot_url = f"https://dmarc-geeks.ch/check?domain={domain}&print=true"
    cta_box = (
        f'<table cellpadding="0" cellspacing="0" border="0" style="width:100%;'
        f'margin:24px 0;border-collapse:separate;">'
        f'<tr><td align="center" style="background:linear-gradient(135deg,#2563eb,#7c3aed);'
        f'border-radius:14px;padding:24px 24px;">'
        f'<div style="color:white;font-family:-apple-system,Inter,sans-serif;'
        f'font-size:16px;font-weight:700;margin-bottom:6px;">📄 Vollständiger 1-Pager-Bericht</div>'
        f'<div style="color:rgba(255,255,255,0.85);font-family:-apple-system,Inter,sans-serif;'
        f'font-size:13px;margin-bottom:14px;line-height:1.5;">'
        f'7 Checks im Detail · druckbar als PDF · perfekt fürs Compliance-Meeting</div>'
        f'<a href="{snapshot_url}" '
        f'style="display:inline-block;background:white;color:#2563eb;text-decoration:none;'
        f'font-family:-apple-system,Inter,sans-serif;font-weight:700;font-size:14.5px;'
        f'padding:13px 28px;border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,0.15);">'
        f'Bericht öffnen →</a>'
        f'<div style="color:rgba(255,255,255,0.7);font-family:-apple-system,Inter,sans-serif;'
        f'font-size:11.5px;margin-top:12px;">Oder einfach kurz antworten — ich schicke ihn dir per Mail.</div>'
        f'</td></tr></table>'
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,'Segoe UI',Inter,sans-serif;color:#1f2937;background:#f8fafc;font-size:14.5px;line-height:1.6;">
<table cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#f8fafc;">
<tr><td align="center" style="padding:24px 12px;">
<table cellpadding="0" cellspacing="0" border="0" style="max-width:640px;width:100%;background:white;border-radius:14px;box-shadow:0 2px 20px rgba(15,23,42,0.06);">
<tr><td style="padding:32px 36px 28px 36px;">

  <p style="margin:0 0 14px 0;">{greeting}</p>

  <p style="margin:0 0 14px 0;">ich habe mir kurz die <strong>Mail-Sicherheit</strong> und die <strong>Zustellbarkeit</strong> von <strong>{domain}</strong> angeschaut — beides hängt an den gleichen drei DNS-Records (SPF / DKIM / DMARC), und ich mache das regelmässig für Schweizer KMU.</p>

  <p style="margin:0 0 22px 0;">{hook}</p>

  <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 22px 0;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:10px;">
    <tr>
      <td style="padding:14px 18px;background:#f8fafc;border-right:1px solid #e2e8f0;width:50%;vertical-align:top;border-radius:10px 0 0 10px;">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#dc2626;margin-bottom:6px;">🛡 Sicherheits-Angle</div>
        <div style="font-size:13.5px;color:#1f2937;line-height:1.55;">Kann jemand in eurem Namen Mails schreiben? Phishing-Angriffe auf Kunden / Lieferanten / Mitarbeitende.</div>
      </td>
      <td style="padding:14px 18px;background:#f8fafc;width:50%;vertical-align:top;border-radius:0 10px 10px 0;">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#d97706;margin-bottom:6px;">📬 Zustellbarkeits-Angle</div>
        <div style="font-size:13.5px;color:#1f2937;line-height:1.55;">Kommen <em>eure</em> Mails (Rechnungen, Termin-Bestätigungen, …) bei Gmail/Outlook/Apple Mail in der Inbox an — oder im Spam?</div>
      </td>
    </tr>
  </table>

  {score_card}

  {snapshot_strip}

  <p style="margin:18px 0 8px 0;font-weight:700;color:#1f2937;">Was ich konkret zuerst angehen würde:</p>
  <ol style="margin:0 0 20px 22px;padding:0;">
    {actions_html}
  </ol>

  {extras_html}

  {industry_cta}

  {cta_box}

  <p style="margin:0 0 18px 0;color:#475569;font-size:13.5px;">Wir bauen sowas regelmässig für Schweizer KMU und MSPs: DMARC-Einführung ohne Mail-Ausfall, ab <strong>CHF 490</strong> als Audit, ab <strong>CHF 1990</strong> als Voll-Migration. Auch als White-Label für Agenturen.</p>

  <p style="margin:0 0 18px 0;">Liebe Grüsse aus dem Zürcher Unterland</p>

  <!-- Signatur-Karte (mit Name + Kontakt — nicht extra "Nils Lappenbusch" davor) -->
  <table cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #e2e8f0;padding-top:18px;margin-top:6px;width:100%;">
    <tr>
      <td valign="middle" style="padding-right:14px;width:50px;">
        <svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="DMARC Geeks" width="48" height="48">
          <defs><linearGradient id="dgCm" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#2563eb"/><stop offset="100%" stop-color="#7c3aed"/></linearGradient></defs>
          <rect width="40" height="40" rx="9" fill="url(#dgCm)"/>
          <path d="M10 17 L10 28 Q10 30 12 30 L28 30 Q30 30 30 28 L30 17 L20 23 Z" fill="#fff"/>
          <circle cx="15" cy="13" r="3" fill="none" stroke="#fff" stroke-width="1.6"/>
          <circle cx="25" cy="13" r="3" fill="none" stroke="#fff" stroke-width="1.6"/>
          <line x1="18" y1="13" x2="22" y2="13" stroke="#fff" stroke-width="1.6"/>
        </svg>
      </td>
      <td valign="middle" style="font-size:13px;line-height:1.55;color:#475569;">
        <div style="color:#1f2937;font-size:14.5px;font-weight:700;">Nils Lappenbusch</div>
        <div style="color:#64748b;font-size:12.5px;margin:2px 0 6px 0;">DMARC Geeks · Mail-Security für KMU</div>
        <div style="font-size:12.5px;">
          <span style="font-weight:600;color:#16a34a;">📞 +41 77 950 31 52</span>
          &nbsp;·&nbsp;
          <a href="mailto:nils@dmarc-geeks.ch" style="color:#2563eb;text-decoration:none;">nils@dmarc-geeks.ch</a>
          &nbsp;·&nbsp;
          <a href="https://dmarc-geeks.ch" style="color:#2563eb;text-decoration:none;">dmarc-geeks.ch</a>
        </div>
      </td>
    </tr>
  </table>

  <p style="margin:18px 0 0 0;font-size:11.5px;color:#94a3b8;line-height:1.55;">
    P.S.: Falls ihr das schon auf dem Schirm habt — gerne ignorieren. Ich schreibe nicht massenhaft, sondern habe gezielt 10–20 Domains aus eurer Branche angeschaut.
  </p>

</td></tr></table>
</td></tr></table>
</body></html>"""

    # Plain-Version (fuer Mail-Clients ohne HTML-Support oder Copy-as-plain)
    plain = render_cold_mail(domain, score, first_name=first_name,
                              company=company, email=email,
                              check_result=check_result)

    return {
        "subject": subject,
        "html": html,
        "plain": plain,
    }
