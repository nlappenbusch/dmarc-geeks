"""Generate 5 realistic DMARC aggregate reports for thesilentwave.de.

Writes both raw .xml and gzipped .xml.gz files plus a manifest.json with
base64-encoded gzip payloads ready for sending as mail attachments.

Run: python scripts/gen_test_dmarc_reports.py
Output: scripts/test_reports/<reporter>!thesilentwave.de!<begin>!<end>.xml.gz
"""
from __future__ import annotations

import base64
import gzip
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT_DIR = Path(__file__).parent / "test_reports"
OUT_DIR.mkdir(exist_ok=True)

DOMAIN = "thesilentwave.de"

# Anchor: yesterday 00:00 UTC -> today 00:00 UTC (24h windows shifted per report)
NOW = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def report_xml(
    org_name: str,
    org_email: str,
    report_id: str,
    begin: datetime,
    end: datetime,
    records: list[dict],
    policy_p: str = "none",
    policy_sp: str = "none",
    policy_pct: int = 100,
) -> str:
    rec_xml = []
    for r in records:
        # Optional auth_results blocks
        dkim_blocks = "\n".join(
            f"""      <dkim>
        <domain>{d['domain']}</domain>
        <selector>{d['selector']}</selector>
        <result>{d['result']}</result>
      </dkim>"""
            for d in r.get("dkim_auth", [])
        )
        spf_blocks = "\n".join(
            f"""      <spf>
        <domain>{s['domain']}</domain>
        <result>{s['result']}</result>
        <scope>mfrom</scope>
      </spf>"""
            for s in r.get("spf_auth", [])
        )
        reason_xml = ""
        if r.get("reason_type"):
            reason_xml = f"""
        <reason>
          <type>{r['reason_type']}</type>
          <comment>{r.get('reason_comment', '')}</comment>
        </reason>"""
        rec_xml.append(
            f"""  <record>
    <row>
      <source_ip>{r['source_ip']}</source_ip>
      <count>{r['count']}</count>
      <policy_evaluated>
        <disposition>{r['disposition']}</disposition>
        <dkim>{r['dkim_eval']}</dkim>
        <spf>{r['spf_eval']}</spf>{reason_xml}
      </policy_evaluated>
    </row>
    <identifiers>
      <header_from>{r.get('header_from', DOMAIN)}</header_from>
    </identifiers>
    <auth_results>
{dkim_blocks}
{spf_blocks}
    </auth_results>
  </record>"""
        )
    records_xml = "\n".join(rec_xml)
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<feedback>
  <report_metadata>
    <org_name>{org_name}</org_name>
    <email>{org_email}</email>
    <report_id>{report_id}</report_id>
    <date_range>
      <begin>{ts(begin)}</begin>
      <end>{ts(end)}</end>
    </date_range>
  </report_metadata>
  <policy_published>
    <domain>{DOMAIN}</domain>
    <adkim>r</adkim>
    <aspf>r</aspf>
    <p>{policy_p}</p>
    <sp>{policy_sp}</sp>
    <pct>{policy_pct}</pct>
  </policy_published>
{records_xml}
</feedback>
"""


# ---------------------------------------------------------------------------
# 5 realistic reports
# ---------------------------------------------------------------------------

REPORTS = [
    # 1. Google – legitimer Outlook-Versand: alles grün
    {
        "org_name": "google.com",
        "org_email": "noreply-dmarc-support@google.com",
        "report_id": f"google-{secrets.token_hex(6)}",
        "begin": NOW - timedelta(days=1),
        "end": NOW,
        "records": [
            {
                "source_ip": "52.101.171.100",  # Outlook 365 EU outbound
                "count": 87,
                "disposition": "none",
                "dkim_eval": "pass",
                "spf_eval": "pass",
                "dkim_auth": [
                    {"domain": DOMAIN, "selector": "selector1", "result": "pass"},
                ],
                "spf_auth": [
                    {"domain": DOMAIN, "result": "pass"},
                ],
            },
        ],
    },
    # 2. Microsoft – Mix: legitim + 1 fremde IP, Outlook bewertet milde (p=none)
    {
        "org_name": "Outlook.com",
        "org_email": "dmarcreport@microsoft.com",
        "report_id": f"outlook-{secrets.token_hex(6)}",
        "begin": NOW - timedelta(days=1),
        "end": NOW,
        "records": [
            {
                "source_ip": "52.101.171.105",  # Outlook
                "count": 42,
                "disposition": "none",
                "dkim_eval": "pass",
                "spf_eval": "pass",
                "dkim_auth": [{"domain": DOMAIN, "selector": "selector1", "result": "pass"}],
                "spf_auth": [{"domain": DOMAIN, "result": "pass"}],
            },
            {
                "source_ip": "185.220.101.55",  # Tor-Exit / Spoofer
                "count": 6,
                "disposition": "none",
                "dkim_eval": "fail",
                "spf_eval": "fail",
                "dkim_auth": [],
                "spf_auth": [{"domain": "spammer.example", "result": "fail"}],
            },
        ],
    },
    # 3. Yahoo – Newsletter via Mailchimp: SPF aligned via DKIM, SPF.mfrom misaligned (typisches ESP-Pattern)
    {
        "org_name": "Yahoo",
        "org_email": "dmarchelp@yahooinc.com",
        "report_id": f"yahoo-{secrets.token_hex(6)}",
        "begin": NOW - timedelta(days=1),
        "end": NOW,
        "records": [
            {
                "source_ip": "198.2.179.123",  # Mailchimp
                "count": 312,
                "disposition": "none",
                "dkim_eval": "pass",
                "spf_eval": "fail",
                "dkim_auth": [{"domain": DOMAIN, "selector": "k1", "result": "pass"}],
                "spf_auth": [{"domain": "mail123.suw15.mcsv.net", "result": "pass"}],
            },
        ],
    },
    # 4. mail.ru – Forwarding-Pattern: SPF fail, DKIM pass = DMARC pass
    {
        "org_name": "Mail.Ru",
        "org_email": "dmarc_support@corp.mail.ru",
        "report_id": f"mailru-{secrets.token_hex(6)}",
        "begin": NOW - timedelta(days=1),
        "end": NOW,
        "records": [
            {
                "source_ip": "94.100.180.31",  # forwarder
                "count": 4,
                "disposition": "none",
                "dkim_eval": "pass",
                "spf_eval": "fail",
                "dkim_auth": [{"domain": DOMAIN, "selector": "selector1", "result": "pass"}],
                "spf_auth": [{"domain": "fwd.mail.ru", "result": "softfail"}],
            },
        ],
    },
    # 5. Fastmail – aggressiver Spoofing-Versuch von Brasilien-IP, alles fail
    {
        "org_name": "Fastmail Pty Ltd",
        "org_email": "dmarc-noreply@fastmail.com",
        "report_id": f"fastmail-{secrets.token_hex(6)}",
        "begin": NOW - timedelta(days=1),
        "end": NOW,
        "records": [
            {
                "source_ip": "177.220.180.42",  # BR residential
                "count": 18,
                "disposition": "none",  # p=none -> nicht quarantined
                "dkim_eval": "fail",
                "spf_eval": "fail",
                "reason_type": "local_policy",
                "reason_comment": "arc=pass",
                "dkim_auth": [],
                "spf_auth": [{"domain": "thesilentwave.de", "result": "fail"}],
            },
            {
                "source_ip": "52.101.171.103",  # parallel: legitimer Outlook
                "count": 12,
                "disposition": "none",
                "dkim_eval": "pass",
                "spf_eval": "pass",
                "dkim_auth": [{"domain": DOMAIN, "selector": "selector1", "result": "pass"}],
                "spf_auth": [{"domain": DOMAIN, "result": "pass"}],
            },
        ],
    },
]


def main() -> None:
    manifest = []
    for r in REPORTS:
        xml = report_xml(
            org_name=r["org_name"],
            org_email=r["org_email"],
            report_id=r["report_id"],
            begin=r["begin"],
            end=r["end"],
            records=r["records"],
        )
        # Filename per DMARC convention: org!domain!begin!end.xml.gz
        org_slug = r["org_name"].lower().replace(" ", "").replace(".", "").replace(",", "")
        fname = f"{org_slug}!{DOMAIN}!{ts(r['begin'])}!{ts(r['end'])}.xml.gz"
        xml_bytes = xml.encode("utf-8")
        gz_bytes = gzip.compress(xml_bytes)
        out_path = OUT_DIR / fname
        out_path.write_bytes(gz_bytes)
        # Also keep plain xml next to it for inspection
        (OUT_DIR / fname.replace(".gz", "")).write_text(xml, encoding="utf-8")
        manifest.append({
            "filename": fname,
            "org_name": r["org_name"],
            "org_email": r["org_email"],
            "report_id": r["report_id"],
            "size_gz": len(gz_bytes),
            "b64": base64.b64encode(gz_bytes).decode("ascii"),
            "subject": f"Report Domain: {DOMAIN} Submitter: {r['org_name']} Report-ID: {r['report_id']}",
        })
        print(f"  + {fname}  ({len(gz_bytes)} B gzipped)")

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"\nManifest: {OUT_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
