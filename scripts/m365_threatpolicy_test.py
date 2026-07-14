#!/usr/bin/env python3
"""M365 Threat-Policy-Tester (CLI) — provoziert unterschiedliche Mail-Handhabung.

Verschickt eine Batterie sorgfaeltig gebauter Test-Mails an ein M365-Postfach.
Jede Mail triggert gezielt einen Defender-/EOP-Policy-Pfad. Ziel: sehen, welche
Mail wo landet — Inbox / Junk / Quarantaene / geblockt (NDR).

Die Test-Faelle + der MIME-Bau liegen in app/threattest.py (geteilt mit der
Web-Seite unter /admin/threattest). Dieses Skript ist der CLI-Aufsatz: Config,
Versand, Ausgabe.

Alle Payloads sind offizielle, harmlose Industrie-Teststrings (EICAR/GTUBE).
KEIN echter Schadcode.

--------------------------------------------------------------------------------
Config: Das Skript laedt SMTP automatisch aus <repo>/.env bzw. /app/.env
(im Container). Alternativ per Shell-Env setzen:

  export SMTP_HOST=mail.pc4play.de
  export SMTP_PORT=587
  export SMTP_USER=postfach@pc4play.de
  export SMTP_PASSWORD=<passwort>     # SMTP_PASS wird auch akzeptiert
  export SMTP_FROM=postfach@pc4play.de

Nutzung:

  python3 m365_threatpolicy_test.py postfach@deine-domain.de           # senden
  python3 m365_threatpolicy_test.py postfach@x.de --dry-run            # nur bauen
  python3 m365_threatpolicy_test.py postfach@x.de --only malware,gtube # Teilmenge
  python3 m365_threatpolicy_test.py --list                             # Faelle
  python3 m365_threatpolicy_test.py postfach@x.de --spoof-from ceo@deine-domain.de
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone

# Repo-Root auf den Pfad, damit `app.threattest` importierbar ist — egal ob
# lokal aus scripts/ oder im Container aus /app gestartet.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.threattest import build_message, make_cases  # noqa: E402

# Windows-Konsole ist oft cp1252 und kann die Emoji-Ausgabe nicht encoden.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

import secrets  # noqa: E402
from typing import Optional  # noqa: E402


def load_env_file(explicit: Optional[str] = None) -> Optional[str]:
    """Laedt SMTP-Vars aus einer .env in os.environ (echte Env gewinnt).

    Sucht: --env-file, dann $DMARC_ENV, dann <repo>/.env, dann /app/.env. So
    laeuft das Tool produktiv per `docker compose exec app python scripts/...`
    ohne dass die SMTP-Vars extra als Container-Environment gesetzt sein muessen.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [explicit, os.environ.get("DMARC_ENV"),
                  os.path.join(here, "..", ".env"), "/app/.env"]
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(),
                                      val.strip().strip('"').strip("'"))
        return os.path.abspath(path)
    return None


def smtp_password() -> str:
    """SMTP-Passwort — akzeptiert SMTP_PASS (Skript) ODER SMTP_PASSWORD (App)."""
    pwd = os.environ.get("SMTP_PASS") or os.environ.get("SMTP_PASSWORD")
    if not pwd:
        print("❌ Weder SMTP_PASS noch SMTP_PASSWORD gesetzt.", file=sys.stderr)
        sys.exit(2)
    return pwd


def env_or_die(key: str, default: Optional[str] = None) -> str:
    val = os.environ.get(key, default)
    if not val:
        print(f"❌ Environment-Variable {key} fehlt.", file=sys.stderr)
        sys.exit(2)
    return val


def select_cases(cases, only: Optional[str]):
    if not only:
        return cases
    wanted = {w.strip().lower() for w in only.split(",") if w.strip()}
    sel = [c for c in cases if c.id.lower() in wanted or c.category in wanted]
    if not sel:
        print(f"❌ Keine Faelle passen zu --only {only!r}.", file=sys.stderr)
        print("   IDs:", ", ".join(c.id for c in cases), file=sys.stderr)
        print("   Kategorien:", ", ".join(sorted({c.category for c in cases})),
              file=sys.stderr)
        sys.exit(2)
    return sel


def print_list(cases) -> None:
    print("Verfuegbare Test-Faelle:\n")
    cat = None
    for c in cases:
        if c.category != cat:
            cat = c.category
            print(f"  [{cat}]")
        mark = "  (SKIP)" if c.skip_reason else ""
        print(f"    {c.id:<20} {c.name}{mark}")
        print(f"    {'':<20} -> {c.expected}")
    print("\n  Kategorien fuer --only:",
          ", ".join(sorted({c.category for c in cases})))


def send_batch(cases, run_id: str, recipient: str, dry_run: bool,
               save_eml: bool, delay: float, verbose: bool) -> int:
    outputs = os.path.join(os.path.dirname(__file__), "..", "outputs")

    if dry_run:
        sender = os.environ.get("SMTP_FROM") or os.environ.get(
            "SMTP_USER") or "test@example.com"
    else:
        host = env_or_die("SMTP_HOST")
        port = int(env_or_die("SMTP_PORT", "587"))
        user = env_or_die("SMTP_USER")
        pwd = smtp_password()
        sender = os.environ.get("SMTP_FROM", user)

    def _write_eml(case, msg) -> None:
        os.makedirs(outputs, exist_ok=True)
        path = os.path.join(outputs, f"m365test_{run_id}_{case.id}.eml")
        with open(path, "wb") as fh:
            fh.write(msg.as_bytes())
        print(f"    .eml -> {os.path.relpath(path)}")

    sent = 0
    if dry_run:
        for case in cases:
            if case.skip_reason:
                print(f"⏭  {case.id}: {case.skip_reason}")
                continue
            msg = build_message(case, run_id, sender, recipient)
            print(f"📝 {case.id:<20} From={msg['From']}")
            _write_eml(case, msg)
            sent += 1
        return sent

    ctx = ssl.create_default_context()
    if os.environ.get("SMTP_TLS_VERIFY", "true").lower() in \
            ("false", "0", "no", "off"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
        with server as s:
            if verbose:
                s.set_debuglevel(1)
            s.ehlo()
            if port in (587, 25):
                s.starttls(context=ctx)
                s.ehlo()
            s.login(user, pwd)
            for i, case in enumerate(cases):
                if case.skip_reason:
                    print(f"⏭  {case.id}: {case.skip_reason}")
                    continue
                msg = build_message(case, run_id, sender, recipient)
                try:
                    s.send_message(msg, from_addr=sender, to_addrs=[recipient])
                    print(f"✓ {case.id:<20} -> {recipient}  "
                          f"(erwartet: {case.expected})")
                    if save_eml:
                        _write_eml(case, msg)
                    sent += 1
                except smtplib.SMTPException as exc:
                    print(f"❌ {case.id:<20} Versand-Fehler: {exc}",
                          file=sys.stderr)
                if delay and i < len(cases) - 1:
                    time.sleep(delay)
    except smtplib.SMTPAuthenticationError as exc:
        print(f"❌ SMTP-Login abgelehnt: {exc}", file=sys.stderr)
        return -1
    except (smtplib.SMTPException, OSError) as exc:
        print(f"❌ SMTP-Verbindungsfehler: {exc}", file=sys.stderr)
        return -1
    return sent


def print_evaluation(cases, run_id: str, recipient: str) -> None:
    print("\n" + "=" * 72)
    print(f"AUSWERTUNG  ·  Run-ID {run_id}  ·  Postfach {recipient}")
    print("=" * 72)
    print("Filter-Header:   X-M365Test-Run = " + run_id)
    print("Betreff-Suche:   [M365-TEST][" + run_id + "]\n")
    for c in cases:
        if c.skip_reason:
            continue
        print(f"• {c.id}\n    erwartet: {c.expected}\n    pruefen : {c.check_where}\n")
    print("Wo nachschauen:")
    print("  Inbox / Junk-Ordner   -> direkt im Postfach")
    print("  Quarantaene           -> https://security.microsoft.com/quarantine")
    print("  Was ist wo gelandet?  -> https://security.microsoft.com/messagetrace")
    print("\nDie Differenz zwischen den Faellen = Wirkung deiner Threat-Policies.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="M365 Threat-Policy-Tester (EICAR/GTUBE/Attachment/Spoof).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Payloads sind harmlose Standard-Teststrings. Nur eigenes "
               "Postfach testen.",
    )
    p.add_argument("to", nargs="?", help="Ziel-Postfach (M365)")
    p.add_argument("--only", help="Nur diese Faelle: Case-IDs oder Kategorien, "
                                  "kommagetrennt (z.B. malware,gtube)")
    p.add_argument("--spoof-from", metavar="ADRESSE",
                   help="Spoof/DMARC-Fall aktivieren; From wird gefaelscht "
                        "(nimm DEINE geschuetzte Domain)")
    p.add_argument("--impersonate", metavar="ANZEIGENAME",
                   help="User-Impersonation-Fall aktivieren; testet Defender-"
                        "Impersonation-Schutz fuer diesen Anzeigenamen "
                        "(z.B. \"Regina Knoepfel\")")
    p.add_argument("--dry-run", action="store_true",
                   help="Nicht senden, nur .eml nach outputs/ schreiben")
    p.add_argument("--save-eml", action="store_true",
                   help="Beim echten Versand zusaetzlich .eml speichern")
    p.add_argument("--delay", type=float, default=2.0,
                   help="Sekunden Pause zwischen Mails (Default 2)")
    p.add_argument("--list", action="store_true", help="Faelle auflisten, Ende")
    p.add_argument("--env-file", metavar="PFAD",
                   help="SMTP-Vars aus dieser .env laden (sonst automatisch)")
    p.add_argument("--verbose", "-v", action="store_true", help="SMTP-Debug")
    args = p.parse_args()

    if not args.list:
        loaded = load_env_file(args.env_file)
        if loaded:
            print(f"📄 SMTP-Config geladen aus {loaded}")

    all_cases = make_cases(args.spoof_from, args.impersonate)

    if args.list:
        print_list(all_cases)
        return 0

    if not args.to:
        p.error("Ziel-Postfach fehlt. Beispiel: "
                "python3 m365_threatpolicy_test.py postfach@domain.de")

    cases = select_cases(all_cases, args.only)
    run_id = datetime.now(timezone.utc).strftime("%m%d-%H%M") + "-" + \
        secrets.token_hex(2)

    active = [c for c in cases if not c.skip_reason]
    print(f"M365 Threat-Policy-Test  ·  Run-ID {run_id}")
    print(f"Ziel: {args.to}  ·  {len(active)} Faelle"
          f"{'  (DRY-RUN)' if args.dry_run else ''}\n")

    result = send_batch(cases, run_id, args.to, args.dry_run,
                        args.save_eml, args.delay, args.verbose)
    if result < 0:
        return 1

    print(f"\n{result} Test-Mail(s) "
          f"{'erzeugt' if args.dry_run else 'verschickt'}.")
    if not args.dry_run:
        print("Warte 1-5 Min, dann auswerten (Quarantaene braucht kurz).")
    print_evaluation(cases, run_id, args.to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
