"""Send the 5 generated test DMARC reports to dmarc@dmarc-geeks.ch via
direct MX submission on port 25.

Der Mail-From bleibt eine neutrale Test-Adresse (konfigurierbar via
TEST_SENDER env var, default lab-test@dmarc-geeks.local). Der echte Reporter
(google.com, outlook.com, etc.) steht ausschliesslich im XML-`org_name`/
`org_email` — wo der DMARC-Parser ihn auch erwartet. Es wird nichts geforgt.
"""
from __future__ import annotations

import json
import os
import smtplib
import socket
import sys
from email.message import EmailMessage
from pathlib import Path

import dns.resolver  # pip install dnspython

MANIFEST = Path(__file__).parent / "test_reports" / "manifest.json"
RCPT = os.environ.get("TEST_RCPT", "dmarc@dmarc-geeks.ch")
RCPT_DOMAIN = RCPT.split("@", 1)[1]
# Sender fuer den Mail-Envelope. Bei SMTP-AUTH muss das eine Adresse sein, die
# der authentifizierte User auch senden darf.
TEST_SENDER = os.environ.get("TEST_SENDER", "")
EHLO_HOST = "dmarc-test-lab.local"

# Optional: Authenticated submission (Port 587 STARTTLS).
# Wenn beide gesetzt: nutzt SMTP-AUTH und umgeht damit rspamd-Anti-Spoofing.
# Sonst: direkter MX-Submit auf Port 25 (klappt fuer Cold-SMTP praktisch nie).
SMTP_HOST = os.environ.get("SMTP_HOST", "")  # z.B. mail.pc4play.de
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")


def lookup_mx(domain: str) -> list[tuple[int, str]]:
    answers = dns.resolver.resolve(domain, "MX")
    return sorted([(int(r.preference), str(r.exchange).rstrip(".")) for r in answers])


def main() -> int:
    if not MANIFEST.exists():
        print(f"Manifest nicht gefunden: {MANIFEST}")
        print("Erst `python scripts/gen_test_dmarc_reports.py` laufen lassen.")
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    use_auth = bool(SMTP_HOST and SMTP_USER and SMTP_PASS)
    if use_auth:
        sender = TEST_SENDER or SMTP_USER
        print(f"-> Authenticated Submission {SMTP_HOST}:{SMTP_PORT} (User: {SMTP_USER})")
        print(f"   Mail-From: {sender}\n")
    else:
        sender = TEST_SENDER or "lab-test@example.com"
        # Note: MX für dmarc-geeks.ch ist kaputt (fehlender trailing dot in zone).
        # Direkt an die bekannte Mailcow-IP gehen.
        mx_host = "162.55.89.34"  # mail.pc4play.de
        print(f"-> Cold-SMTP-Submit {mx_host}:25 (kein SMTP_AUTH gesetzt)")
        print(f"   Mail-From: {sender}")
        print(f"   ACHTUNG: rspamd lehnt Cold-SMTP fast immer ab — setz SMTP_HOST/USER/PASS\n")

    reports_dir = MANIFEST.parent
    ok, fail = 0, 0
    for entry in manifest:
        gz_path = reports_dir / entry["filename"]
        msg = EmailMessage()
        msg["From"] = f"DMARC Test Lab <{sender}>"
        msg["To"] = RCPT
        msg["Subject"] = entry["subject"]
        msg["Auto-Submitted"] = "auto-generated"
        msg.set_content(
            "Synthetic DMARC aggregate report — generated locally for "
            f"ingest-pipeline testing.\n\nReporter (im XML): {entry['org_name']}\n"
            f"Report-ID: {entry['report_id']}\n"
        )
        gz_bytes = gz_path.read_bytes()
        msg.add_attachment(
            gz_bytes,
            maintype="application",
            subtype="gzip",
            filename=entry["filename"],
        )

        try:
            if use_auth:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                    s.ehlo(EHLO_HOST)
                    s.starttls()
                    s.ehlo(EHLO_HOST)
                    s.login(SMTP_USER, SMTP_PASS)
                    s.send_message(msg, from_addr=sender, to_addrs=[RCPT])
            else:
                with smtplib.SMTP("162.55.89.34", 25, timeout=15) as s:
                    s.ehlo(EHLO_HOST)
                    try:
                        s.starttls()
                        s.ehlo(EHLO_HOST)
                    except Exception:
                        pass
                    s.send_message(msg, from_addr=sender, to_addrs=[RCPT])
            print(f"  OK   {entry['filename']}")
            ok += 1
        except (smtplib.SMTPException, socket.error, TimeoutError) as e:
            print(f"  FAIL {entry['filename']}: {e}")
            fail += 1

    print(f"\n{ok} OK, {fail} FAIL")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
