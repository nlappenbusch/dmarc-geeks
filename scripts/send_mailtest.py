#!/usr/bin/env python3
"""Schickt eine Test-Mail an den dmarc-geeks Mail-Tester.

Nutzt SMTP von dem Anbieter deiner Wahl (Gmail App-Password, dein Mailcow,
oder ein anderer SMTP-Server).

Setup einmal pro Shell-Session:

  export SMTP_HOST=smtp.gmail.com         # oder mail.pc4play.de
  export SMTP_PORT=587                    # 587 = STARTTLS, 465 = SSL
  export SMTP_USER=nlappenbusch@gmail.com
  export SMTP_PASS=<dein-app-passwort>    # bei Gmail: App-Password generieren!
  export SMTP_FROM=nlappenbusch@gmail.com # darf gleich SMTP_USER sein

Dann senden:

  python3 send_mailtest.py mt-r96jvyycr79n@mt.dmarc-geeks.ch

Optional: Subject + Body über CLI-Args:

  python3 send_mailtest.py mt-XXX@mt.dmarc-geeks.ch \\
      --subject "Mein Test" --body "Hallo Welt"
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid, formatdate


def env_or_die(key: str, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    if not val:
        print(f"❌ Environment-Variable {key} fehlt.", file=sys.stderr)
        print("   Beispiel: export SMTP_HOST=smtp.gmail.com", file=sys.stderr)
        sys.exit(2)
    return val


def main() -> int:
    p = argparse.ArgumentParser(description="Test-Mail an Mail-Tester schicken")
    p.add_argument("to", help="Empfänger-Adresse (mt-TOKEN@mt.dmarc-geeks.ch)")
    p.add_argument("--subject", default="Mail-Tester Test "
                    + datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
    p.add_argument("--body", default=None)
    p.add_argument("--html", action="store_true",
                    help="Body auch als HTML mitschicken (mail-tester gibt dann mehr Punkte)")
    p.add_argument("--verbose", "-v", action="store_true",
                    help="SMTP-Dialog im Detail anzeigen")
    args = p.parse_args()

    host = env_or_die("SMTP_HOST")
    port = int(env_or_die("SMTP_PORT", "587"))
    user = env_or_die("SMTP_USER")
    pwd  = env_or_die("SMTP_PASS")
    sender = os.environ.get("SMTP_FROM", user)

    body_text = args.body or (
        "Hallo,\n\n"
        "dies ist eine Test-Mail an den dmarc-geeks Mail-Tester.\n"
        "Der Score wird gleich auf https://dmarc-geeks.ch/mailtest/<token> sichtbar.\n\n"
        "Falls du diese Mail aus Versehen bekommst — bitte ignorieren, ist nur "
        "ein automatischer Sanity-Check.\n\n"
        "Beste Grüsse,\n"
        f"{sender}\n"
    )

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = args.to
    msg["Subject"] = args.subject
    msg["Reply-To"] = sender
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
    msg["X-Mailer"] = "dmarc-geeks-mailtest-script/1.0"
    msg.set_content(body_text)

    if args.html:
        # HTML-Alternative — Mail-Tester gibt Bonuspunkte für multipart/alternative
        body_html = (
            "<html><body style='font-family:-apple-system,Segoe UI,Inter,sans-serif;color:#1f2937;'>"
            f"<p>{body_text.replace(chr(10), '<br>')}</p>"
            "<p style='color:#94a3b8;font-size:12px;'>"
            "Generiert mit <code>send_mailtest.py</code> · dmarc-geeks.ch"
            "</p></body></html>"
        )
        msg.add_alternative(body_html, subtype="html")

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                if args.verbose:
                    s.set_debuglevel(1)
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                if args.verbose:
                    s.set_debuglevel(1)
                s.ehlo()
                if port in (587, 25):
                    s.starttls(context=ctx)
                    s.ehlo()
                s.login(user, pwd)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ SMTP-Login abgelehnt: {e}", file=sys.stderr)
        print("   Bei Gmail: 2FA aktiv? Dann brauchst du ein App-Password "
              "(myaccount.google.com → Security → App passwords)", file=sys.stderr)
        return 1
    except smtplib.SMTPException as e:
        print(f"❌ SMTP-Fehler: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"❌ Verbindungsfehler {host}:{port} — {e}", file=sys.stderr)
        return 1

    print(f"✓ Mail an {args.to} via {host}:{port} verschickt.")
    print(f"  Check Status: https://dmarc-geeks.ch{(' /admin/system' if 'mt-' in args.to else '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
