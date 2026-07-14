#!/usr/bin/env python3
"""M365 Threat-Policy-Tester — provoziert unterschiedliche Handhabung von Test-Mails.

Verschickt eine Batterie sorgfältig gebauter Test-Mails an ein M365-Postfach.
Jede Mail ist so konstruiert, dass sie einen bestimmten Defender-/EOP-Policy-Pfad
triggert. Ziel: sehen, welche Mail wo landet — Inbox / Junk / Quarantäne / geblockt
(NDR). Genau diese Differenz macht die Wirkung der Threat-Policies sichtbar.

Alle Payloads sind offizielle, harmlose Industrie-Teststrings:

  * EICAR  — Standard-Antivirus-Testdatei (triggert Anti-Malware)
  * GTUBE  — Generic Test for Unsolicited Bulk Email (triggert Anti-Spam)
  * GTPHISH — Phishing-Teststring (triggert Anti-Phishing, experimentell)
  * harmlose Dateien mit "gefährlicher" Endung (triggert Common-Attachment-Filter)

KEIN echter Schadcode. EICAR & GTUBE sind genau für solche Tests gedacht.

--------------------------------------------------------------------------------
Setup (einmal pro Shell-Session), identisch zu send_mailtest.py:

  export SMTP_HOST=smtp.gmail.com      # oder mail.pc4play.de
  export SMTP_PORT=587                 # 587 = STARTTLS, 465 = SSL
  export SMTP_USER=nlappenbusch@gmail.com
  export SMTP_PASS=<app-passwort>
  export SMTP_FROM=nlappenbusch@gmail.com

Senden an das zu testende M365-Postfach:

  python3 m365_threatpolicy_test.py postfach@deine-domain.de

Nur bestimmte Fälle (Case-ID oder Kategorie):

  python3 m365_threatpolicy_test.py postfach@x.de --only eicar-zip,gtube
  python3 m365_threatpolicy_test.py postfach@x.de --only malware,attachment

Erst mal ansehen ohne zu senden (schreibt .eml nach outputs/):

  python3 m365_threatpolicy_test.py postfach@x.de --dry-run

Alle Fälle auflisten:

  python3 m365_threatpolicy_test.py --list

Anti-Spoofing/DMARC mittesten (From wird gefälscht — nimm DEINE geschützte Domain):

  python3 m365_threatpolicy_test.py postfach@x.de --spoof-from ceo@deine-domain.de
"""
from __future__ import annotations

import argparse
import io
import os
import secrets
import smtplib
import ssl
import struct
import sys
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Callable, Optional

# Windows-Konsole ist oft cp1252 und kann die Emoji-Ausgabe nicht encoden.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# --------------------------------------------------------------------------- #
# Standard-Teststrings (harmlos, industrieweit für genau diesen Zweck gemacht)
# --------------------------------------------------------------------------- #

# EICAR-Antivirus-Testdatei. Wird von JEDEM AV/Defender als "Testvirus" erkannt.
# Absichtlich hier gesplittet, damit dieses Skript selbst nicht als Virus anschlägt.
EICAR = (
    r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR"
    r"-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
).encode("ascii")

# GTUBE — Spam-Teststring. EOP wertet das als hohen Spam-Score (SCL 9).
GTUBE = "XJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X"

# GTPHISH — Phishing-Teststring (nicht offiziell von MS dokumentiert, aber von
# mehreren Filtern unterstützt). Experimentell — kann, muss aber nicht anschlagen.
GTPHISH = "XJS*C4JDBQADN1.NSBN3*2IDNEN*GTPHISH-STANDARD-ANTI-PHISH-TEST-EMAIL*C.34X"

# Harmloser Inhalt für die "gefährliche Endung"-Attachment-Tests.
HARMLESS = (
    b"Dies ist eine harmlose Testdatei fuer M365-Threat-Policy-Tests.\r\n"
    b"Kein ausfuehrbarer Code, kein Makro, keine Payload.\r\n"
    b"Zweck: den Common-Attachment-Filter ueber die Datei-Endung ausloesen.\r\n"
)

# Harmlose Test-URL fuer den Safe-Links-Test (existiert, ist unverfaenglich).
SAFELINKS_URL = "https://www.microsoft.com/security/business/threat-protection"


# --------------------------------------------------------------------------- #
# ZipCrypto — passwortgeschütztes ZIP ohne Fremd-Abhängigkeit (stdlib-only).
# Damit lässt sich "unscannbares" verschlüsseltes Archiv testen (EOP kann rein
# nicht scannen -> je nach Policy Quarantäne "unscannable" oder Zustellung).
# --------------------------------------------------------------------------- #

def _crc_table() -> list[int]:
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (0xEDB88320 ^ (c >> 1)) if (c & 1) else (c >> 1)
        tab.append(c)
    return tab


_CRCTAB = _crc_table()


class _ZipKeys:
    """Traditionelle PKWARE-Verschluesselung (ZipCrypto)."""

    def __init__(self, password: bytes) -> None:
        self.k0, self.k1, self.k2 = 0x12345678, 0x23456789, 0x34567890
        for b in password:
            self._update(b)

    def _update(self, b: int) -> None:
        self.k0 = (self.k0 >> 8) ^ _CRCTAB[(self.k0 ^ b) & 0xFF]
        self.k1 = (self.k1 + (self.k0 & 0xFF)) & 0xFFFFFFFF
        self.k1 = (self.k1 * 134775813 + 1) & 0xFFFFFFFF
        self.k2 = (self.k2 >> 8) ^ _CRCTAB[(self.k2 ^ (self.k1 >> 24)) & 0xFF]

    def _stream(self) -> int:
        t = (self.k2 | 2) & 0xFFFF
        return ((t * (t ^ 1)) >> 8) & 0xFF

    def encrypt(self, data: bytes) -> bytes:
        out = bytearray()
        for p in data:
            out.append(p ^ self._stream())
            self._update(p)
        return bytes(out)


def _encrypted_zip(inner_name: str, data: bytes, password: str) -> bytes:
    """Baut ein traditionell-verschluesseltes ZIP (Store, kein Deflate)."""
    pwd = password.encode()
    crc = zlib.crc32(data) & 0xFFFFFFFF

    # 12-Byte Encryption-Header; letztes Byte = High-Byte der CRC (Check-Byte).
    header = bytearray(os.urandom(11))
    header.append((crc >> 24) & 0xFF)
    keys = _ZipKeys(pwd)
    enc = keys.encrypt(bytes(header) + data)

    name = inner_name.encode()
    comp_size = len(enc)
    uncomp_size = len(data)
    flag = 0x0001  # Bit 0 = verschluesselt
    # Lokaler Datei-Header
    local = struct.pack(
        "<IHHHHHIIIHH",
        0x04034B50, 20, flag, 0, 0, 0, crc, comp_size, uncomp_size,
        len(name), 0,
    ) + name
    local_off = 0
    body = local + enc
    # Central-Directory-Header
    central = struct.pack(
        "<IHHHHHHIIIHHHHHII",
        0x02014B50, 20, 20, flag, 0, 0, 0, crc, comp_size, uncomp_size,
        len(name), 0, 0, 0, 0, 0, local_off,
    ) + name
    # End-of-Central-Directory
    eocd = struct.pack(
        "<IHHHHIIH",
        0x06054B50, 0, 0, 1, 1, len(central), len(body), 0,
    )
    blob = body + central + eocd

    # Selbsttest: mit stdlib wieder entschluesseln -> muss identisch sein.
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
        zf.setpassword(pwd)
        if zf.read(inner_name) != data:
            raise ValueError("Roundtrip-Mismatch")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ZipCrypto-Selbsttest fehlgeschlagen: {exc}") from exc
    return blob


def _plain_zip(inner_name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, data)
    return buf.getvalue()


def _nested_zip(inner_name: str, data: bytes, depth: int = 2) -> bytes:
    """Verschachteltes ZIP (ZIP-in-ZIP) — testet Scan-Tiefe des Archiv-Scanners."""
    blob = data
    name = inner_name
    for i in range(depth):
        blob = _plain_zip(name, blob)
        name = f"layer{i}.zip"
    return blob


# --------------------------------------------------------------------------- #
# Test-Fall-Definition
# --------------------------------------------------------------------------- #

@dataclass
class TestCase:
    id: str
    name: str
    category: str            # Slug fuer --only (spam, malware, attachment, ...)
    expected: str            # erwartete Handhabung
    check_where: str         # wo nachschauen
    build: Callable[[EmailMessage], None]
    header_from: Optional[str] = None   # gesetzter From-Header (Spoof-Test)
    skip_reason: Optional[str] = None   # gefuellt, wenn Fall nicht baubar


def _base_text(case_id: str, expected: str, extra: str = "") -> str:
    return (
        "M365 Threat-Policy-Test\r\n"
        "=======================\r\n\r\n"
        f"Test-Fall : {case_id}\r\n"
        f"Erwartung : {expected}\r\n\r\n"
        "Diese Mail ist ein automatischer Threat-Policy-Test. Sie enthaelt keinen\r\n"
        "echten Schadcode — nur harmlose Industrie-Teststrings (EICAR/GTUBE).\r\n"
        "Wenn du sie unerwartet bekommst: bitte ignorieren.\r\n"
        f"{extra}"
    )


def make_cases(spoof_from: Optional[str]) -> list[TestCase]:
    cases: list[TestCase] = []

    # --- Baseline ----------------------------------------------------------- #
    def b_control(m: EmailMessage) -> None:
        m.set_content(_base_text(
            "control", "Inbox (Zustellung)",
            "\r\nReiner Kontroll-Fall ohne Payload — sollte normal zugestellt werden.\r\n"
        ))
    cases.append(TestCase(
        "control", "Sauberer Kontroll-Fall", "baseline",
        "Zustellung in die Inbox",
        "Inbox — Baseline, bestaetigt dass Zustellung ueberhaupt klappt.",
        b_control,
    ))

    # --- Anti-Spam ---------------------------------------------------------- #
    def b_gtube(m: EmailMessage) -> None:
        m.set_content(_base_text(
            "gtube", "Junk oder Quarantaene (Spam)",
            f"\r\nGTUBE-Spam-Teststring:\r\n{GTUBE}\r\n"
        ))
    cases.append(TestCase(
        "gtube", "GTUBE Spam-Test", "spam",
        "Junk-Ordner oder Spam-Quarantaene (SCL 9)",
        "Junk-Ordner ODER Quarantaene (je nach Spam-Action der Anti-Spam-Policy).",
        b_gtube,
    ))

    # --- Anti-Phishing (experimentell) -------------------------------------- #
    def b_gtphish(m: EmailMessage) -> None:
        m.set_content(_base_text(
            "gtphish", "Quarantaene/Junk (Phishing) — experimentell",
            f"\r\nGTPHISH-Phishing-Teststring:\r\n{GTPHISH}\r\n"
        ))
    cases.append(TestCase(
        "gtphish", "GTPHISH Phishing-Test", "phishing",
        "Phishing-Handling (experimentell, nicht offiziell von MS garantiert)",
        "Junk/Quarantaene falls unterstuetzt — sonst Inbox (dann greift der Test nicht).",
        b_gtphish,
    ))

    # --- Anti-Malware: EICAR-Varianten -------------------------------------- #
    def _eicar_attach(m: EmailMessage, filename: str, payload: bytes,
                      maintype: str, subtype: str) -> None:
        m.set_content(_base_text(
            m["Subject"] or "eicar", "Malware-Quarantaene",
            f"\r\nEICAR-Testdatei im Anhang: {filename}\r\n"
        ))
        m.add_attachment(payload, maintype=maintype, subtype=subtype,
                         filename=filename)

    cases.append(TestCase(
        "eicar-txt", "EICAR als .txt", "malware",
        "Malware-Quarantaene",
        "Quarantaene (Portal: security.microsoft.com/quarantine) — Malware-Detection.",
        lambda m: _eicar_attach(m, "eicar.txt", EICAR, "text", "plain"),
    ))
    cases.append(TestCase(
        "eicar-com", "EICAR als .com", "malware",
        "Malware-Quarantaene",
        "Quarantaene — .com-Endung + EICAR-Signatur.",
        lambda m: _eicar_attach(m, "eicar.com", EICAR,
                                "application", "octet-stream"),
    ))
    cases.append(TestCase(
        "eicar-zip", "EICAR in .zip", "malware",
        "Malware-Quarantaene",
        "Quarantaene — Archiv-Scanner muss ins ZIP schauen.",
        lambda m: _eicar_attach(m, "eicar.zip",
                                _plain_zip("eicar.com", EICAR),
                                "application", "zip"),
    ))
    cases.append(TestCase(
        "eicar-nested-zip", "EICAR in ZIP-in-ZIP", "malware",
        "Malware-Quarantaene ODER Zustellung (Policy-Luecke!)",
        "Wenn zugestellt -> Scan-Tiefe zu gering: verschachtelte Archive werden "
        "nicht erkannt. Genau so eine Differenz willst du sehen.",
        lambda m: _eicar_attach(m, "eicar.zip",
                                _nested_zip("eicar.com", EICAR, depth=3),
                                "application", "zip"),
    ))

    # Passwort-ZIP (unscannbar). Kann bauen fehlschlagen -> sauber skippen.
    try:
        enc_zip = _encrypted_zip("eicar.com", EICAR, "infected")
        cases.append(TestCase(
            "eicar-password-zip", "EICAR in Passwort-ZIP (unscannbar)", "malware",
            "Quarantaene 'unscannable' ODER Zustellung",
            "Passwort 'infected'. EOP kann nicht reinschauen -> je nach Policy "
            "Quarantaene (unscannable) oder Zustellung. Klassischer Bypass-Test.",
            lambda m, z=enc_zip: _eicar_attach(m, "eicar_infected.zip", z,
                                               "application", "zip"),
        ))
    except Exception as exc:  # noqa: BLE001
        cases.append(TestCase(
            "eicar-password-zip", "EICAR in Passwort-ZIP", "malware",
            "-", "-", lambda m: None,
            skip_reason=f"Verschluesseltes ZIP nicht baubar: {exc}",
        ))

    # --- Common-Attachment-Filter (blockt nach Datei-Endung/True-Type) ------ #
    def _harmless_attach(m: EmailMessage, filename: str) -> None:
        m.set_content(_base_text(
            "attachment", "Block durch Common-Attachment-Filter",
            f"\r\nHarmlose Datei mit auffaelliger Endung im Anhang: {filename}\r\n"
        ))
        m.add_attachment(HARMLESS, maintype="application",
                         subtype="octet-stream", filename=filename)

    for ext, cid in (("exe", "attach-exe"), ("js", "attach-js"),
                     ("hta", "attach-hta")):
        cases.append(TestCase(
            cid, f"Harmlose Datei als .{ext}", "attachment",
            "Block/Quarantaene durch Common-Attachment-Filter",
            "Quarantaene/geblockt allein wegen der Endung — Inhalt ist harmlos.",
            lambda m, f=f"testdatei.{ext}": _harmless_attach(m, f),
        ))
    cases.append(TestCase(
        "attach-double-ext", "Doppel-Endung rechnung.pdf.exe", "attachment",
        "Block durch Common-Attachment-Filter",
        "Quarantaene/geblockt — testet Umgang mit getarnter Doppel-Endung.",
        lambda m: _harmless_attach(m, "rechnung.pdf.exe"),
    ))

    # --- Safe Links --------------------------------------------------------- #
    def b_safelinks(m: EmailMessage) -> None:
        m.set_content(_base_text(
            "safelinks-url", "Zustellung mit umgeschriebenem Link",
            f"\r\nTest-URL im Body: {SAFELINKS_URL}\r\n"
        ))
        html = (
            "<html><body>"
            f"<p>Safe-Links-Test. Link: <a href='{SAFELINKS_URL}'>{SAFELINKS_URL}</a></p>"
            "</body></html>"
        )
        m.add_alternative(html, subtype="html")
    cases.append(TestCase(
        "safelinks-url", "Safe-Links URL-Rewrite", "safelinks",
        "Zustellung, aber Link umgeschrieben auf *.safelinks.protection.outlook.com",
        "Inbox — dann im Link pruefen ob URL zu safelinks.protection.outlook.com "
        "umgeschrieben wurde (Safe Links aktiv?).",
        b_safelinks,
    ))

    # --- Anti-Spoofing / DMARC (opt-in) ------------------------------------- #
    if spoof_from:
        def b_spoof(m: EmailMessage) -> None:
            m.set_content(_base_text(
                "spoof-from", "Spoof-Detection / DMARC quarantine/reject",
                f"\r\nGefaelschter From-Header: {spoof_from}\r\n"
                "Envelope-Absender bleibt dein authentifizierter SMTP-User.\r\n"
            ))
        cases.append(TestCase(
            "spoof-from", f"From-Spoof ({spoof_from})", "spoof",
            "Spoof-Intelligence/DMARC: Quarantaene, Junk oder Reject",
            "Quarantaene/Junk (Spoof) bzw. Reject falls DMARC p=reject auf der "
            "gespooften Domain. Direkt relevant fuer den DMARC-Aggregator.",
            b_spoof, header_from=spoof_from,
        ))

    return cases


# --------------------------------------------------------------------------- #
# Versand / CLI
# --------------------------------------------------------------------------- #

def load_env_file(explicit: Optional[str] = None) -> Optional[str]:
    """Laedt SMTP-Vars aus einer .env-Datei in os.environ (echte Env gewinnt).

    Sucht: --env-file, dann $DMARC_ENV, dann <repo>/.env (lokal), dann
    /app/.env (im Container gemountet). So laeuft das Tool produktiv per
    `docker compose exec app python scripts/m365_threatpolicy_test.py` ohne
    dass die SMTP-Vars extra als Container-Environment gesetzt sein muessen.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        explicit,
        os.environ.get("DMARC_ENV"),
        os.path.join(here, "..", ".env"),
        "/app/.env",
    ]
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                # setdefault: bereits gesetzte echte Env-Vars nicht ueberschreiben
                os.environ.setdefault(key.strip(),
                                      val.strip().strip('"').strip("'"))
        return os.path.abspath(path)
    return None


def smtp_password() -> str:
    """SMTP-Passwort — akzeptiert SMTP_PASS (Skript-Konvention) ODER
    SMTP_PASSWORD (App-/prod-.env-Konvention)."""
    pwd = os.environ.get("SMTP_PASS") or os.environ.get("SMTP_PASSWORD")
    if not pwd:
        print("❌ Weder SMTP_PASS noch SMTP_PASSWORD gesetzt.", file=sys.stderr)
        print("   Setze eins davon (App-.env nutzt SMTP_PASSWORD).",
              file=sys.stderr)
        sys.exit(2)
    return pwd


def env_or_die(key: str, default: Optional[str] = None) -> str:
    val = os.environ.get(key, default)
    if not val:
        print(f"❌ Environment-Variable {key} fehlt.", file=sys.stderr)
        print("   Beispiel: export SMTP_HOST=smtp.gmail.com", file=sys.stderr)
        sys.exit(2)
    return val


def select_cases(cases: list[TestCase], only: Optional[str]) -> list[TestCase]:
    if not only:
        return cases
    wanted = {w.strip().lower() for w in only.split(",") if w.strip()}
    sel = [c for c in cases if c.id.lower() in wanted or c.category in wanted]
    if not sel:
        print(f"❌ Keine Faelle passen zu --only {only!r}.", file=sys.stderr)
        print("   Verfuegbar (IDs):", ", ".join(c.id for c in cases), file=sys.stderr)
        cats = sorted({c.category for c in cases})
        print("   Kategorien:", ", ".join(cats), file=sys.stderr)
        sys.exit(2)
    return sel


def print_list(cases: list[TestCase]) -> None:
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


def build_message(case: TestCase, run_id: str, sender: str,
                  recipient: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"[M365-TEST][{run_id}][{case.id}] {case.name}"
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
    msg["X-Mailer"] = "dmarc-geeks-m365-threattest/1.0"
    msg["X-M365Test-Run"] = run_id
    msg["X-M365Test-Case"] = case.id
    msg["X-M365Test-Category"] = case.category
    case.build(msg)
    # From zuletzt setzen (Spoof-Faelle ueberschreiben den echten Absender).
    msg["From"] = case.header_from or sender
    return msg


def send_batch(cases: list[TestCase], run_id: str, recipient: str,
               dry_run: bool, save_eml: bool, delay: float,
               verbose: bool) -> int:
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

    def _write_eml(case: TestCase, msg: EmailMessage) -> None:
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
                    # Envelope-Absender = authentifizierter User, auch bei Spoof.
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
        print("   Bei Gmail: App-Password noetig (2FA).", file=sys.stderr)
        return -1
    except (smtplib.SMTPException, OSError) as exc:
        print(f"❌ SMTP-Verbindungsfehler: {exc}", file=sys.stderr)
        return -1
    return sent


def print_evaluation(cases: list[TestCase], run_id: str, recipient: str) -> None:
    print("\n" + "=" * 72)
    print(f"AUSWERTUNG  ·  Run-ID {run_id}  ·  Postfach {recipient}")
    print("=" * 72)
    print("Filter im Betreff/Header setzen:  X-M365Test-Run = " + run_id)
    print("Oder Betreff-Suche:               [M365-TEST][" + run_id + "]\n")
    for c in cases:
        if c.skip_reason:
            continue
        print(f"• {c.id}")
        print(f"    erwartet: {c.expected}")
        print(f"    pruefen : {c.check_where}\n")
    print("Wo nachschauen:")
    print("  Inbox / Junk-Ordner      -> direkt im Postfach")
    print("  Quarantaene              -> https://security.microsoft.com/quarantine")
    print("  Was ist wo gelandet?     -> Message Trace: "
          "https://security.microsoft.com/messagetrace")
    print("  Threat-Explorer (P2)     -> https://security.microsoft.com/threatexplorer")
    print("\nDie Differenz zwischen den Faellen = Wirkung deiner Threat-Policies.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="M365 Threat-Policy-Tester — provoziert unterschiedliche "
                    "Mail-Handhabung (EICAR/GTUBE/Attachment/Spoof).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Payloads sind harmlose Standard-Teststrings. Nur eigenes "
               "Postfach testen.",
    )
    p.add_argument("to", nargs="?", help="Ziel-Postfach (M365)")
    p.add_argument("--only", help="Nur diese Faelle: Case-IDs oder Kategorien, "
                                  "kommagetrennt (z.B. malware,gtube)")
    p.add_argument("--spoof-from", metavar="ADRESSE",
                   help="Anti-Spoofing/DMARC-Fall aktivieren; From wird auf diese "
                        "Adresse gefaelscht (nimm DEINE geschuetzte Domain)")
    p.add_argument("--dry-run", action="store_true",
                   help="Nicht senden, nur .eml nach outputs/ schreiben")
    p.add_argument("--save-eml", action="store_true",
                   help="Beim echten Versand zusaetzlich .eml speichern")
    p.add_argument("--delay", type=float, default=2.0,
                   help="Sekunden Pause zwischen Mails (Default 2)")
    p.add_argument("--list", action="store_true", help="Faelle auflisten, Ende")
    p.add_argument("--env-file", metavar="PFAD",
                   help="SMTP-Vars aus dieser .env laden (sonst automatisch "
                        "<repo>/.env bzw. /app/.env)")
    p.add_argument("--verbose", "-v", action="store_true", help="SMTP-Debug")
    args = p.parse_args()

    # SMTP-Config aus .env nachladen, falls nicht schon als Env-Var gesetzt.
    if not args.list:
        loaded = load_env_file(args.env_file)
        if loaded:
            print(f"📄 SMTP-Config geladen aus {loaded}")

    all_cases = make_cases(args.spoof_from)

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
