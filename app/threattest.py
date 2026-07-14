"""M365 Threat-Policy-Test — geteilte Kern-Logik.

Definiert die Test-Faelle und baut die MIME-Nachrichten. Reine Logik, kein
SMTP/kein IO — damit sowohl das CLI-Skript (scripts/m365_threatpolicy_test.py)
als auch der Web-Router (app/routers/threattest.py) dieselbe Quelle nutzen.

Alle Payloads sind offizielle, harmlose Industrie-Teststrings (EICAR/GTUBE).
KEIN echter Schadcode.
"""
from __future__ import annotations

import io
import os
import struct
import zipfile
import zlib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Callable, Optional

# --------------------------------------------------------------------------- #
# Standard-Teststrings (harmlos, industrieweit fuer genau diesen Zweck gemacht)
# --------------------------------------------------------------------------- #

# EICAR-Antivirus-Testdatei. Absichtlich gesplittet, damit dieses Modul selbst
# nicht von einem Scanner als Virus angeschlagen wird.
EICAR = (
    r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR"
    r"-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
).encode("ascii")

# GTUBE — Spam-Teststring (EOP wertet das als SCL 9).
GTUBE = "XJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X"

# GTPHISH — Phishing-Teststring (experimentell, nicht offiziell von MS).
GTPHISH = "XJS*C4JDBQADN1.NSBN3*2IDNEN*GTPHISH-STANDARD-ANTI-PHISH-TEST-EMAIL*C.34X"

# Harmloser Inhalt fuer die "gefaehrliche Endung"-Attachment-Tests.
HARMLESS = (
    b"Dies ist eine harmlose Testdatei fuer M365-Threat-Policy-Tests.\r\n"
    b"Kein ausfuehrbarer Code, kein Makro, keine Payload.\r\n"
    b"Zweck: den Common-Attachment-Filter ueber die Datei-Endung ausloesen.\r\n"
)

SAFELINKS_URL = "https://www.microsoft.com/security/business/threat-protection"

# AMTSO-Phishing-Test-Seite: vendor-neutrale, sichere URL zum Testen von
# Anti-Phishing/URL-Reputation (keine echte Phishing-Seite, kein Schadcode).
AMTSO_PHISH_URL = "https://www.amtso.org/feature-settings-check-phishing-page/"


# --------------------------------------------------------------------------- #
# ZipCrypto — passwortgeschuetztes ZIP ohne Fremd-Abhaengigkeit (stdlib-only).
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


def encrypted_zip(inner_name: str, data: bytes, password: str) -> bytes:
    """Baut ein traditionell-verschluesseltes ZIP (Store) + Roundtrip-Selbsttest."""
    pwd = password.encode()
    crc = zlib.crc32(data) & 0xFFFFFFFF

    header = bytearray(os.urandom(11))
    header.append((crc >> 24) & 0xFF)  # Check-Byte = High-Byte der CRC
    keys = _ZipKeys(pwd)
    enc = keys.encrypt(bytes(header) + data)

    name = inner_name.encode()
    comp_size, uncomp_size, flag = len(enc), len(data), 0x0001
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flag, 0, 0, 0, crc,
                        comp_size, uncomp_size, len(name), 0) + name
    body = local + enc
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flag, 0, 0,
                          0, crc, comp_size, uncomp_size, len(name), 0, 0, 0, 0,
                          0, 0) + name
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central),
                       len(body), 0)
    blob = body + central + eocd

    zf = zipfile.ZipFile(io.BytesIO(blob))
    zf.setpassword(pwd)
    if zf.read(inner_name) != data:
        raise RuntimeError("ZipCrypto-Selbsttest fehlgeschlagen")
    return blob


def plain_zip(inner_name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, data)
    return buf.getvalue()


def nested_zip(inner_name: str, data: bytes, depth: int = 2) -> bytes:
    """Verschachteltes ZIP (ZIP-in-ZIP) — testet Scan-Tiefe des Archiv-Scanners."""
    blob, name = data, inner_name
    for i in range(depth):
        blob = plain_zip(name, blob)
        name = f"layer{i}.zip"
    return blob


# --------------------------------------------------------------------------- #
# Test-Fall-Definition
# --------------------------------------------------------------------------- #

@dataclass
class TestCase:
    id: str
    name: str
    category: str            # Slug fuer Auswahl (spam, malware, attachment, ...)
    expected: str            # erwartete Handhabung
    check_where: str         # wo nachschauen
    build: Callable[[EmailMessage], None]
    header_from: Optional[str] = None   # gesetzter From-Header (Spoof-Test)
    impersonate_name: Optional[str] = None  # From-Anzeigename (Impersonation-Test)
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


def make_cases(spoof_from: Optional[str] = None,
               impersonate: Optional[str] = None) -> list[TestCase]:
    """Baut die vollstaendige Fall-Liste.

    spoof_from aktiviert den Spoof-Fall; impersonate (Anzeigename eines zu
    schuetzenden Users) aktiviert den User-Impersonation-Fall.
    """
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
        "Meist nur generischer Spam (GTPHISH ist KEIN offizieller MS-Trigger)",
        "Landet i.d.R. als Spam (General filter, CAT:SPM), nicht als echter "
        "Phishing-Verdikt — MS kennt GTPHISH nicht. Header X-Forefront-Antispam-"
        "Report zeigt CAT: und SCL:.",
        b_gtphish,
    ))

    # Phishing-Test-URL (AMTSO) — zielt via URL-Reputation auf Phish/HPHISH.
    def b_phishurl(m: EmailMessage) -> None:
        m.set_content(_base_text(
            "phish-url", "Phishing / High-conf-Phishing via URL-Reputation",
            "\r\nSicherheitshinweis: Ihr Konto muss bestaetigt werden.\r\n"
            f"Bitte hier anmelden: {AMTSO_PHISH_URL}\r\n"
        ))
        html = (
            "<html><body><p>Ihr Konto wurde voruebergehend gesperrt. "
            f"<a href='{AMTSO_PHISH_URL}'>Jetzt anmelden und verifizieren</a>, "
            "um die Sperre aufzuheben.</p></body></html>"
        )
        m.add_alternative(html, subtype="html")
    cases.append(TestCase(
        "phish-url", "Phishing-Test-URL (AMTSO)", "phishing",
        "Phishing / High-conf-Phishing via URL-Reputation (nicht 100% deterministisch)",
        "Header X-Forefront-Antispam-Report pruefen: CAT:PHISH bzw. CAT:HPHSH = "
        "Phishing-Verdikt; CAT:SPM/HSPM = nur Spam. Safe Links kann die URL "
        "zusaetzlich umschreiben.",
        b_phishurl,
    ))

    # --- Anti-Malware: EICAR-Varianten -------------------------------------- #
    def _eicar_attach(m: EmailMessage, filename: str, payload: bytes,
                      maintype: str, subtype: str) -> None:
        m.set_content(_base_text(
            filename, "Malware-Quarantaene",
            f"\r\nEICAR-Testdatei im Anhang: {filename}\r\n"
        ))
        m.add_attachment(payload, maintype=maintype, subtype=subtype,
                         filename=filename)

    cases.append(TestCase(
        "eicar-txt", "EICAR als .txt", "malware", "Malware-Quarantaene",
        "Quarantaene (security.microsoft.com/quarantine) — Malware-Detection.",
        lambda m: _eicar_attach(m, "eicar.txt", EICAR, "text", "plain"),
    ))
    cases.append(TestCase(
        "eicar-com", "EICAR als .com", "malware", "Malware-Quarantaene",
        "Quarantaene — .com-Endung + EICAR-Signatur.",
        lambda m: _eicar_attach(m, "eicar.com", EICAR, "application",
                                "octet-stream"),
    ))
    cases.append(TestCase(
        "eicar-zip", "EICAR in .zip", "malware", "Malware-Quarantaene",
        "Quarantaene — Archiv-Scanner muss ins ZIP schauen.",
        lambda m: _eicar_attach(m, "eicar.zip", plain_zip("eicar.com", EICAR),
                                "application", "zip"),
    ))
    cases.append(TestCase(
        "eicar-nested-zip", "EICAR in ZIP-in-ZIP", "malware",
        "Malware-Quarantaene ODER Zustellung (Policy-Luecke!)",
        "Wenn zugestellt -> Scan-Tiefe zu gering: verschachtelte Archive werden "
        "nicht erkannt. Genau so eine Differenz willst du sehen.",
        lambda m: _eicar_attach(m, "eicar.zip",
                                nested_zip("eicar.com", EICAR, depth=3),
                                "application", "zip"),
    ))

    # Passwort-ZIP (unscannbar). Bau kann fehlschlagen -> sauber skippen.
    try:
        enc = encrypted_zip("eicar.com", EICAR, "infected")
        cases.append(TestCase(
            "eicar-password-zip", "EICAR in Passwort-ZIP (unscannbar)", "malware",
            "Quarantaene 'unscannable' ODER Zustellung",
            "Passwort 'infected'. EOP kann nicht reinschauen -> je nach Policy "
            "Quarantaene (unscannable) oder Zustellung. Klassischer Bypass-Test.",
            lambda m, z=enc: _eicar_attach(m, "eicar_infected.zip", z,
                                           "application", "zip"),
        ))
    except Exception as exc:  # noqa: BLE001
        cases.append(TestCase(
            "eicar-password-zip", "EICAR in Passwort-ZIP", "malware", "-", "-",
            lambda m: None,
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
        html = (f"<html><body><p>Safe-Links-Test. Link: "
                f"<a href='{SAFELINKS_URL}'>{SAFELINKS_URL}</a></p></body></html>")
        m.add_alternative(html, subtype="html")
    cases.append(TestCase(
        "safelinks-url", "Safe-Links URL-Rewrite", "safelinks",
        "Zustellung, aber Link umgeschrieben auf *.safelinks.protection.outlook.com",
        "Inbox — dann pruefen ob URL zu safelinks.protection.outlook.com "
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

    # --- User-Impersonation (opt-in) ---------------------------------------- #
    # Testet den Defender-Impersonation-Schutz: From-ANZEIGENAME = geschuetzter
    # User, Absender-ADRESSE aber extern (unser Sender). Genau die "Chef-Masche".
    if impersonate:
        name = impersonate.strip()

        def b_imp(m: EmailMessage) -> None:
            m.set_content(_base_text(
                "impersonation", "User-Impersonation -> Quarantaene",
                f"\r\nDiese Mail gibt sich per Anzeigename als '{name}' aus,\r\n"
                "kommt aber von der externen Test-Adresse. Der Defender-\r\n"
                "Impersonation-Schutz sollte das als User-Impersonation erkennen.\r\n"
            ))
        cases.append(TestCase(
            "impersonation", f"User-Impersonation ({name})", "impersonation",
            "Quarantaene (User-Impersonation)",
            "Quarantaene mit Grund 'Impersonation'; Defender-Portal -> "
            "'View impersonations'. Greift nur, wenn der Name als geschuetzter "
            "User in der Anti-Phishing-Policy hinterlegt ist.",
            b_imp, impersonate_name=name,
        ))

    return cases


def build_message(case: TestCase, run_id: str, sender: str,
                  recipient: str) -> EmailMessage:
    """Baut die fertige MIME-Nachricht fuer einen Fall."""
    msg = EmailMessage()
    msg["Subject"] = f"[M365-TEST][{run_id}][{case.id}] {case.name}"
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1]
                                   if "@" in sender else "localhost")
    msg["X-Mailer"] = "dmarc-geeks-m365-threattest/1.0"
    msg["X-M365Test-Run"] = run_id
    msg["X-M365Test-Case"] = case.id
    msg["X-M365Test-Category"] = case.category
    case.build(msg)
    # From zuletzt setzen:
    #  - Impersonation: Anzeigename = geschuetzter User, Adresse = echter Sender
    #  - Spoof: kompletter gefaelschter From-Header
    #  - sonst: echter Sender
    if case.impersonate_name:
        msg["From"] = formataddr((case.impersonate_name, sender))
    else:
        msg["From"] = case.header_from or sender
    return msg
