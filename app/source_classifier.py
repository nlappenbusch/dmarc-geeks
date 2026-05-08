"""Source-IP-Classifier — kategorisiert Sender-Quellen anhand:
- bekannten Provider-Hostnamen (Mailchimp, SendGrid, Google, M365, …)
- Pass-Rate (legitim vs. verdächtig)
- Volumen (steady vs. neu vs. spike)
- Match mit MX-Records (eigener Server)

Inspiriert von dmarcian's „Source Classifier" — wir bauen eine pragmatische
Regel-basierte Variante, die aus den Daten die wir eh haben
(PTR-Hostname + Pass-Rate + Volumen-Trend) eine Klassifikation ableitet.
"""
from __future__ import annotations

import re
from typing import Optional


# Provider-Pattern auf PTR-Hostnamen — match in Reihenfolge, erstes Match gewinnt
PROVIDER_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, provider_name, category)
    # category: 'mailbox' (M365/Google/etc.), 'marketing' (Bulk-Sender),
    # 'crm' (CRM/SaaS-Tools), 'ch_special' (CH-Mail-Encryption)

    # Mail-Hosting / Mailbox-Provider
    (r"\.outbound\.protection\.outlook\.com$|\.smtp\.office365\.com$|\.olc\.protection\.outlook\.com$",
        "Microsoft 365", "mailbox"),
    (r"\.google\.com$|\.googlemail\.com$|\.gmail\.com$",
        "Google Workspace", "mailbox"),
    (r"\.icloud\.com$|\.mail\.icloud\.com$|\.apple\.com$",
        "Apple iCloud", "mailbox"),
    (r"\.mail\.protonmail\.ch$|\.protonmail\.ch$|\.proton\.me$",
        "Proton Mail", "mailbox"),
    (r"\.mail\.yandex\.net$",
        "Yandex Mail", "mailbox"),
    (r"\.mailbox\.org$",
        "mailbox.org", "mailbox"),
    (r"\.posteo\.(de|net)$",
        "Posteo", "mailbox"),
    (r"\.tutanota\.de$",
        "Tuta", "mailbox"),
    (r"\.fastmail\.com$|\.messagingengine\.com$",
        "Fastmail", "mailbox"),
    (r"\.zoho\.com$|\.zoho\.eu$",
        "Zoho Mail", "mailbox"),
    (r"\.kundenserver\.de$|\.online\.de$",
        "IONOS / 1&1", "mailbox"),
    (r"\.strato\.de$",
        "Strato", "mailbox"),
    (r"\.infomaniak\.com$|\.ik-server\.com$",
        "Infomaniak", "mailbox"),
    (r"\.hostpoint\.ch$",
        "Hostpoint", "mailbox"),
    (r"\.cyon\.ch$",
        "cyon", "mailbox"),
    (r"\.mailcow\..*$",
        "Mailcow (self-hosted)", "mailbox"),

    # Marketing / Bulk-Sender
    (r"\.brevo\.com$|\.sendinblue\.com$",
        "Brevo (Sendinblue)", "marketing"),
    (r"\.mcsv\.net$|\.mailchimpapp\.com$|\.rsgsv\.net$|\.list-manage\.com$",
        "Mailchimp", "marketing"),
    (r"\.mandrillapp\.com$",
        "Mandrill", "marketing"),
    (r"\.sendgrid\.net$|\.sendgrid\.com$",
        "SendGrid", "marketing"),
    (r"\.mailgun\.org$|\.mailgun\.net$",
        "Mailgun", "marketing"),
    (r"\.amazonses\.com$|\.amazonaws\.com$",
        "AWS SES", "marketing"),
    (r"\.klaviyo\.com$|\.klaviyomail\.com$",
        "Klaviyo", "marketing"),
    (r"\.salesforce\.com$|\.exacttarget\.com$|\.pardot\.com$",
        "Salesforce / Pardot", "marketing"),
    (r"\.sparkpostmail\.com$|\.sparkpost\.com$",
        "SparkPost", "marketing"),
    (r"\.mtasv\.net$|\.postmark\.com$|\.postmarkapp\.com$",
        "Postmark", "marketing"),
    (r"\.activecampaign\.com$|\.activehosted\.com$",
        "ActiveCampaign", "marketing"),
    (r"\.constantcontact\.com$",
        "Constant Contact", "marketing"),
    (r"\.everlytic\.net$",
        "Everlytic", "marketing"),

    # CRM / SaaS
    (r"\.hubspotemail\.net$|\.hubspot\.com$",
        "HubSpot", "crm"),
    (r"\.intercom\.io$|\.intercom-mail\.com$",
        "Intercom", "crm"),
    (r"\.pipedrive\.com$|\.pipedriveassist\.com$",
        "Pipedrive", "crm"),
    (r"\.zendesk\.com$",
        "Zendesk", "crm"),
    (r"\.freshdesk\.com$|\.freshmail\.com$",
        "Freshdesk", "crm"),
    (r"\.docusign\.net$",
        "DocuSign", "crm"),
    (r"\.atlassian\.net$|\.atlassian\.com$",
        "Atlassian (Jira/Confluence)", "crm"),
    (r"\.shopify\.com$|\.shopifyemail\.com$",
        "Shopify", "crm"),
    (r"\.notion\.so$",
        "Notion", "crm"),
    (r"\.calendly\.com$",
        "Calendly", "crm"),

    # CH-Special
    (r"\.seppmail\.ch$",
        "SeppMail", "ch_special"),
    (r"\.hin\.ch$",
        "HIN (Health Info Net)", "ch_special"),

    # Mimecast / Proofpoint / Barracuda (Mail-Gateways)
    (r"\.mimecast\.com$|\.mimecast\.net$|\.cust-spam\.com$",
        "Mimecast", "gateway"),
    (r"\.pphosted\.com$|\.proofpoint\.com$",
        "Proofpoint", "gateway"),
    (r"\.barracudanetworks\.com$|\.cudasvc\.com$",
        "Barracuda", "gateway"),
]


def classify_source(
    *,
    ip: str,
    hostname: Optional[str],
    pass_count: int,
    fail_count: int,
    total_count: int,
    is_mx_ip: bool = False,
    is_in_allowlist: bool = False,
    days_seen: int = 1,
) -> dict:
    """Classify a sender source.

    Returns dict:
      - category: one of 'own' | 'mailbox' | 'marketing' | 'crm' | 'gateway' | 'ch_special' |
                  'unknown' | 'forwarder' | 'spoofer'
      - label: human-readable label
      - confidence: 'high' | 'medium' | 'low'
      - provider: matched provider name or None
      - flags: list of strings — semantic markers like 'high_volume', 'low_pass_rate'
    """
    out: dict = {
        "category": "unknown",
        "label": "Unbekannt",
        "confidence": "low",
        "provider": None,
        "flags": [],
    }

    pass_rate = (pass_count / total_count * 100.0) if total_count else 0.0

    # Allowlist trumps alles
    if is_in_allowlist:
        out["category"] = "own"
        out["label"] = "In Allowlist (manuell verifiziert)"
        out["confidence"] = "high"
        return out

    # Eigener MX = eigener Mailserver
    if is_mx_ip:
        out["category"] = "own"
        out["label"] = "Eigener Mailserver (MX-IP)"
        out["confidence"] = "high"
        return out

    # PTR-Hostname-Match
    if hostname:
        host = hostname.strip(".").lower()
        for pattern, provider, category in PROVIDER_PATTERNS:
            if re.search(pattern, host):
                out["category"] = category
                out["provider"] = provider
                out["label"] = provider
                out["confidence"] = "high"
                if pass_rate < 50 and total_count > 10:
                    out["flags"].append("low_pass_rate")
                    out["label"] = f"{provider} (mit Auth-Problemen)"
                return out

    # Kein Match — klassifiziere via Pass-Rate + Volumen
    if total_count >= 100 and pass_rate >= 95:
        # Hohes Volumen + hohe Pass-Rate = sehr wahrscheinlich legitim, nur unbekannter Provider
        out["category"] = "mailbox"
        out["label"] = "Vermutlich legitim (unbekannter Provider)"
        out["confidence"] = "medium"
    elif total_count >= 10 and pass_rate >= 80:
        out["category"] = "unknown"
        out["label"] = "Unbekannt — wahrscheinlich legitim"
        out["confidence"] = "medium"
    elif total_count >= 5 and pass_rate < 30:
        # Niedrige Pass-Rate, ständig dabei — entweder Spoofer oder kaputter Sender
        if fail_count > 50 and days_seen <= 7:
            out["category"] = "spoofer"
            out["label"] = "Verdächtig (Spoofing-Versuche?)"
            out["confidence"] = "medium"
            out["flags"].append("low_pass_rate")
            out["flags"].append("recent")
        else:
            out["category"] = "unknown"
            out["label"] = "Auth-Probleme — prüfen"
            out["confidence"] = "low"
            out["flags"].append("low_pass_rate")
    elif fail_count > 0 and pass_count > 0 and abs(fail_count - pass_count) / total_count < 0.3:
        # Mixed — könnte Forwarder sein (DKIM-pass, SPF-fail typisch)
        out["category"] = "forwarder"
        out["label"] = "Forwarder (DKIM-pass, SPF-fail)"
        out["confidence"] = "low"
    else:
        out["category"] = "unknown"
        out["label"] = "Unbekannte Quelle"
        out["confidence"] = "low"

    if total_count >= 1000:
        out["flags"].append("high_volume")
    if days_seen <= 1:
        out["flags"].append("new")

    return out


def category_meta(category: str) -> dict:
    """Return display metadata for a category."""
    metas = {
        "own":         {"icon": "🏠", "color": "var(--ok)",     "label": "Eigen"},
        "mailbox":     {"icon": "📨", "color": "var(--brand)",  "label": "Mail-Hosting"},
        "marketing":   {"icon": "📢", "color": "#d97706",       "label": "Marketing"},
        "crm":         {"icon": "🤝", "color": "#7c3aed",       "label": "CRM/SaaS"},
        "gateway":     {"icon": "🛡️", "color": "#0891b2",       "label": "Mail-Gateway"},
        "ch_special":  {"icon": "🇨🇭", "color": "#dc2626",       "label": "CH-Spezial"},
        "forwarder":   {"icon": "🔀", "color": "#64748b",       "label": "Forwarder"},
        "spoofer":     {"icon": "🎭", "color": "var(--bad)",    "label": "Verdächtig"},
        "unknown":     {"icon": "❓", "color": "var(--muted)",  "label": "Unbekannt"},
    }
    return metas.get(category, metas["unknown"])
