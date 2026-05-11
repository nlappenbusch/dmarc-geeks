"""Sender-Knowledge-Base: kuratierte Datenbank bekannter E-Mail-Sender mit
DMARC-Capability + Setup-Guides.

Inspiriert von dmarc.io (dmarcian's public DB). Wir starten klein und ehrlich:
~30 Sender abdecken die typisch 90%+ KMU-Traffic ausmachen.

Jeder Sender bekommt:
- name, slug, category (mailbox/marketing/crm/transactional/gateway/ch_special)
- dmarc_capable: 'yes' / 'partial' / 'configurable' / 'no'
- spf_guide: URL / Anweisungen / None
- dkim_guide: URL / Anweisungen / None
- notes: kurzer Pragma-Text
- public_url: offizielle Anbieter-Doku
- ptr_patterns: Regex-Liste fuer PTR-Hostnamen (matched mit source_classifier.py)

URL-Schema: /sender/<slug>  -> SEO-tauglich, indexierbar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Sender:
    slug: str
    name: str
    category: str  # mailbox / marketing / crm / transactional / gateway / ch_special
    dmarc_capable: str  # yes / partial / configurable / no
    description: str
    spf_guide: Optional[str] = None
    dkim_guide: Optional[str] = None
    public_url: Optional[str] = None
    notes: Optional[str] = None
    ptr_patterns: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)  # alternative Namen fuer Suche


# ============================================================================
# Kuratierte DB — ~40 Sender, deckt 95%+ KMU-Traffic ab
# ============================================================================

_DB: list[Sender] = [
    # ===== Mailbox / Mail-Hosting =====
    Sender(
        slug="microsoft-365",
        name="Microsoft 365 (Exchange Online)",
        category="mailbox",
        dmarc_capable="yes",
        description="Microsofts Cloud-Mail-Service. Sehr breit eingesetzt — wahrscheinlich der häufigste Sender in DACH-KMU.",
        spf_guide="Im DNS: include:spf.protection.outlook.com hinzufügen. Achtung: Microsoft frisst je nach Region 1-2 weitere Lookups.",
        dkim_guide="Im Microsoft 365 Admin Center: Security → Email authentication → DKIM → Domain auswählen → Activate. DKIM-CNAMEs werden danach generiert und müssen ins DNS.",
        public_url="https://learn.microsoft.com/en-us/microsoft-365/security/office-365-security/email-authentication-anti-spoofing",
        ptr_patterns=[r"\.outbound\.protection\.outlook\.com$", r"\.smtp\.office365\.com$"],
        aliases=["m365", "office365", "exchange-online", "EOP"],
    ),
    Sender(
        slug="google-workspace",
        name="Google Workspace (Gmail Business)",
        category="mailbox",
        dmarc_capable="yes",
        description="Googles Cloud-Mail-Service. DMARC out-of-the-box gut konfiguriert wenn man SPF und DKIM aktiviert.",
        spf_guide="Im DNS: include:_spf.google.com. Single Lookup, super sauber.",
        dkim_guide="Google Admin Console → Apps → Google Workspace → Gmail → Authenticate email → Generate new record. Selector ist 'google'.",
        public_url="https://support.google.com/a/answer/180504",
        ptr_patterns=[r"\.google\.com$", r"\.googlemail\.com$"],
        aliases=["gmail", "g-suite"],
    ),
    Sender(
        slug="infomaniak",
        name="Infomaniak",
        category="mailbox",
        dmarc_capable="yes",
        description="Schweizer Mail-Hoster, sehr beliebt bei KMU. Datenhaltung in CH.",
        spf_guide="include:spf.infomaniak.ch — sauber, 1 Lookup.",
        dkim_guide="Infomaniak Admin → Mail → Service → DKIM aktivieren. Selector 'infomaniak'.",
        public_url="https://faq.infomaniak.com/2535",
        ptr_patterns=[r"\.infomaniak\.com$", r"\.ik-server\.com$"],
        aliases=["infomaniak.ch"],
    ),
    Sender(
        slug="hostpoint",
        name="Hostpoint",
        category="mailbox",
        dmarc_capable="yes",
        description="Schweizer Hosting-Anbieter mit Mail-Service. Sehr verbreitet bei kleineren KMU.",
        spf_guide="include:_spf.hostpoint.ch",
        dkim_guide="Im Hostpoint Control Panel: Mail → Domain → DKIM-Schlüssel erzeugen → Public-Key als TXT ins DNS.",
        public_url="https://support.hostpoint.ch",
        ptr_patterns=[r"\.hostpoint\.ch$"],
        aliases=["hostpoint.ch"],
    ),
    Sender(
        slug="cyon",
        name="cyon",
        category="mailbox",
        dmarc_capable="yes",
        description="Basler Hoster mit eigenem Mail-Service. CH-Datenhaltung.",
        spf_guide="include:_spf.cyon.ch",
        dkim_guide="cyon my!-Panel: Mailings → DKIM für Domain aktivieren.",
        public_url="https://www.cyon.ch/support",
        ptr_patterns=[r"\.cyon\.ch$"],
    ),
    Sender(
        slug="proton-mail",
        name="Proton Mail",
        category="mailbox",
        dmarc_capable="yes",
        description="End-to-End-verschlüsselter Mail-Service aus der Schweiz. Custom-Domain-Support im Business-Plan.",
        spf_guide="include:_spf.protonmail.ch",
        dkim_guide="Proton Admin → Domains → DKIM → Selector + Public Key → ins DNS.",
        public_url="https://proton.me/support",
        ptr_patterns=[r"\.protonmail\.ch$", r"\.proton\.me$"],
        aliases=["protonmail"],
    ),
    Sender(
        slug="apple-icloud",
        name="Apple iCloud Custom Domain",
        category="mailbox",
        dmarc_capable="yes",
        description="iCloud+ erlaubt Custom-Domain-Mail. Selten in KMU, gelegentlich bei Solo-Unternehmern.",
        spf_guide="include:icloud.com",
        dkim_guide="Apple richtet DKIM automatisch ein wenn die Domain validiert ist.",
        public_url="https://support.apple.com/en-us/HT212524",
        ptr_patterns=[r"\.icloud\.com$", r"\.mail\.icloud\.com$"],
    ),
    Sender(
        slug="mailbox-org",
        name="mailbox.org",
        category="mailbox",
        dmarc_capable="yes",
        description="Berliner Anbieter mit hohem Datenschutz-Anspruch. Beliebt bei Konsumenten + Solo-Unternehmern.",
        spf_guide="include:mailbox.org",
        dkim_guide="mailbox.org Admin → Domain → DKIM aktivieren → Schlüssel ins DNS kopieren.",
        public_url="https://kb.mailbox.org",
        ptr_patterns=[r"\.mailbox\.org$"],
    ),
    Sender(
        slug="ionos",
        name="IONOS / 1&1",
        category="mailbox",
        dmarc_capable="configurable",
        description="Großer DE-Hoster. Standard-Setup funktioniert, aber DKIM ist nicht out-of-the-box aktiv — muss explizit eingerichtet werden.",
        spf_guide="include:_spf-eu.ionos.com — neue Generation. Achtung: alte Domains haben oft kundenserver.de-Patterns die separat behandelt werden müssen.",
        dkim_guide="IONOS-Login → E-Mail-Verwaltung → Domain-Einstellungen → DKIM aktivieren. Setup dauert ~24h bis DNS-Propagation greift.",
        public_url="https://www.ionos.de/hilfe/e-mail/dmarc/",
        ptr_patterns=[r"\.kundenserver\.de$", r"\.online\.de$"],
        aliases=["1und1", "1-und-1"],
    ),
    Sender(
        slug="strato",
        name="Strato",
        category="mailbox",
        dmarc_capable="configurable",
        description="DE-Hoster, Mid-Market. DKIM-Setup ist über das Strato-Panel verfügbar, aber etwas umständlich.",
        spf_guide="include:_spf.strato.de",
        dkim_guide="Im Strato-Kunden-Login: E-Mail → Domain → DKIM-Selector erstellen → Public-Key ins DNS.",
        public_url="https://www.strato.de/faq/",
        ptr_patterns=[r"\.strato\.de$"],
    ),
    Sender(
        slug="zoho-mail",
        name="Zoho Mail",
        category="mailbox",
        dmarc_capable="yes",
        description="Günstige Mail-Alternative zu Microsoft 365 / Google Workspace. Gut für kleine Teams.",
        spf_guide="include:zoho.com (oder zoho.eu für EU-Hosting).",
        dkim_guide="Zoho Admin → Mail Admin → DKIM → Selector + Domain → Public-Key generieren.",
        public_url="https://www.zoho.com/mail/help/adminconsole/dkim-configuration.html",
        ptr_patterns=[r"\.zoho\.com$", r"\.zoho\.eu$"],
    ),
    Sender(
        slug="fastmail",
        name="Fastmail",
        category="mailbox",
        dmarc_capable="yes",
        description="Australischer Mail-Service mit guter UX und Custom-Domain-Support.",
        spf_guide="include:spf.messagingengine.com",
        dkim_guide="Fastmail richtet DKIM automatisch ein wenn die Custom-Domain validiert ist (mehrere Selectors).",
        public_url="https://www.fastmail.help/hc/en-us",
        ptr_patterns=[r"\.messagingengine\.com$"],
    ),
    Sender(
        slug="mailcow",
        name="Mailcow (self-hosted)",
        category="mailbox",
        dmarc_capable="yes",
        description="Open-Source Self-Hosted Mail-Stack. SPF/DKIM/DMARC alles im Web-UI konfigurierbar. Wir nutzen es selbst.",
        spf_guide="In deinem Mailcow-UI: Configuration → Domains → SPF-Hinweis kopieren. Selber ins DNS.",
        dkim_guide="Mailcow → Configuration → Domains → DKIM keys generieren → ARC-Key auch direkt aktivieren.",
        public_url="https://docs.mailcow.email",
        ptr_patterns=[r"\.mailcow\..*$"],
    ),

    # ===== Marketing / Newsletter =====
    Sender(
        slug="mailchimp",
        name="Mailchimp",
        category="marketing",
        dmarc_capable="configurable",
        description="Der Klassiker für E-Mail-Newsletter. DMARC-konform aber nur mit korrektem Custom-Domain-Setup.",
        spf_guide="Mailchimp NICHT in dein SPF aufnehmen (sie verwenden hidden mail-domains). Stattdessen: ihre eigene Domain-Authentication-Flow durchklicken — das setzt SPF+DKIM via CNAME-Records.",
        dkim_guide="Mailchimp → Brand → Domains → Authenticate domain → 2 CNAME-Records ins DNS.",
        public_url="https://mailchimp.com/help/about-email-authentication/",
        notes="Vorsicht: viele KMUs setzen include:servers.mcsv.net im SPF — das ist DEPRECATED und macht DMARC kaputt. Stattdessen Domain-Authentication-Flow.",
        ptr_patterns=[r"\.mcsv\.net$", r"\.mailchimpapp\.com$", r"\.rsgsv\.net$", r"\.list-manage\.com$"],
    ),
    Sender(
        slug="brevo",
        name="Brevo (ehemals Sendinblue)",
        category="marketing",
        dmarc_capable="yes",
        description="Französischer Newsletter-Anbieter, EU-DSGVO-tauglich. Sauberer DMARC-Setup über Custom-Domain-Authentication.",
        spf_guide="Brevo → Senders & IPs → Domain authentication → SPF-Record als TXT.",
        dkim_guide="Brevo Domain-Authentication-Flow gibt dir DKIM-Public-Key + Selector. Selector ist meist 'mail'.",
        public_url="https://help.brevo.com/hc/en-us/articles/12163873383186",
        ptr_patterns=[r"\.brevo\.com$", r"\.sendinblue\.com$"],
        aliases=["sendinblue"],
    ),
    Sender(
        slug="sendgrid",
        name="SendGrid (Twilio)",
        category="transactional",
        dmarc_capable="yes",
        description="Transactional-Mail-Backbone für viele SaaS-Apps (Rechnungen, Recovery-Links, Bestätigungen).",
        spf_guide="include:sendgrid.net — empfohlen statt SendGrid in own SPF zu inkludieren.",
        dkim_guide="SendGrid → Settings → Sender Authentication → Authenticate Domain. Wizard erzeugt CNAME-Records.",
        public_url="https://docs.sendgrid.com/ui/account-and-settings/how-to-set-up-domain-authentication",
        ptr_patterns=[r"\.sendgrid\.net$", r"\.sendgrid\.com$"],
    ),
    Sender(
        slug="mailgun",
        name="Mailgun",
        category="transactional",
        dmarc_capable="yes",
        description="Developer-fokussierter Transactional-Mail-Service. API-First.",
        spf_guide="include:mailgun.org oder pro Region include:eu._spf.mailgun.org.",
        dkim_guide="Mailgun Dashboard → Sending → Domains → Domain auswählen → DKIM authority key → Public-Key ins DNS.",
        public_url="https://help.mailgun.com/hc/en-us/articles/202256730",
        ptr_patterns=[r"\.mailgun\.org$", r"\.mailgun\.net$"],
    ),
    Sender(
        slug="postmark",
        name="Postmark",
        category="transactional",
        dmarc_capable="yes",
        description="Hochwertiger Transactional-Mail-Service, Fokus auf hohe Zustellrate.",
        spf_guide="include:spf.mtasv.net",
        dkim_guide="Postmark → Servers → Sender Signatures → DKIM CNAME-Record ins DNS.",
        public_url="https://postmarkapp.com/support/article/1188-what-is-dkim-and-how-do-i-add-my-postmark-server-key",
        ptr_patterns=[r"\.mtasv\.net$", r"\.postmarkapp\.com$"],
    ),
    Sender(
        slug="aws-ses",
        name="Amazon SES",
        category="transactional",
        dmarc_capable="yes",
        description="AWS Simple Email Service. Sehr günstig in den Versandkosten, aber Setup ist developer-lastig.",
        spf_guide="include:amazonses.com",
        dkim_guide="AWS SES Console → Verified identities → Identity → DKIM-Setup → 3 CNAME-Records ins DNS.",
        public_url="https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim.html",
        ptr_patterns=[r"\.amazonses\.com$"],
    ),
    Sender(
        slug="klaviyo",
        name="Klaviyo",
        category="marketing",
        dmarc_capable="yes",
        description="E-Commerce-fokussierter Newsletter-Anbieter, Shopify-/WooCommerce-Integration.",
        spf_guide="Custom-Domain-Authentication-Flow benutzen — Klaviyo nicht in own SPF aufnehmen.",
        dkim_guide="Klaviyo → Settings → Email → Dedicated Sending Domain → Add. 4 CNAME-Records ins DNS.",
        public_url="https://help.klaviyo.com/hc/en-us/articles/115002091871",
        ptr_patterns=[r"\.klaviyo\.com$", r"\.klaviyomail\.com$"],
    ),
    Sender(
        slug="activecampaign",
        name="ActiveCampaign",
        category="marketing",
        dmarc_capable="configurable",
        description="Marketing-Automation + CRM-Hybrid.",
        spf_guide="include:_spf.activecampaign.com (achtung — eskaliert die Lookup-Zahl deines SPF).",
        dkim_guide="ActiveCampaign → Settings → Advanced → DKIM authentication → 2 CNAME-Records.",
        public_url="https://help.activecampaign.com/hc/en-us/articles/207317485",
        ptr_patterns=[r"\.activecampaign\.com$", r"\.activehosted\.com$"],
    ),
    Sender(
        slug="constant-contact",
        name="Constant Contact",
        category="marketing",
        dmarc_capable="partial",
        description="Älterer US-Marketing-Anbieter. DMARC ist konfigurierbar, aber nicht out-of-the-box ideal.",
        spf_guide="include:spf.constantcontact.com",
        dkim_guide="Constant Contact Support kontaktieren — DKIM-Setup nicht selbst-bedienbar.",
        public_url="https://knowledgebase.constantcontact.com/email-digital-marketing/articles/KnowledgeBase/5870-authenticate-emails-with-self-authentication",
        ptr_patterns=[r"\.constantcontact\.com$"],
    ),

    # ===== CRM / SaaS =====
    Sender(
        slug="hubspot",
        name="HubSpot",
        category="crm",
        dmarc_capable="yes",
        description="CRM mit Marketing-Email-Engine. Sehr beliebt im DACH-Mid-Market.",
        spf_guide="Custom-Domain-Authentication nutzen, NICHT HubSpot in own SPF inkludieren.",
        dkim_guide="HubSpot Settings → Marketing → Email → Configuration → Domain Authentication. 2 CNAME-Records ins DNS.",
        public_url="https://knowledge.hubspot.com/email-deliverability/connect-your-email-sending-domain",
        ptr_patterns=[r"\.hubspotemail\.net$", r"\.hubspot\.com$"],
    ),
    Sender(
        slug="pipedrive",
        name="Pipedrive",
        category="crm",
        dmarc_capable="partial",
        description="Sales-CRM. Sendet Mails über eigene Domain, DMARC-Alignment ist suboptimal.",
        spf_guide="Pipedrive empfiehlt include:spf.pipedrive.com — aber Achtung: viele KMU sehen damit DMARC-fail weil Pipedrive die From-Domain nicht alignt.",
        dkim_guide="Pipedrive → Sales Inbox → Settings → Email Tracking. DKIM ist nicht überall konfigurierbar — Support kontaktieren bei Problemen.",
        public_url="https://support.pipedrive.com/en/article/email-sync",
        notes="Bekanntes Pain-Point: Pipedrive-Mails fallen oft durch DMARC alignment durch. Workaround: From-Adresse auf eine Sub-Domain ohne strikte DMARC.",
        ptr_patterns=[r"\.pipedrive\.com$"],
    ),
    Sender(
        slug="salesforce",
        name="Salesforce / Pardot",
        category="crm",
        dmarc_capable="yes",
        description="Enterprise-CRM. Marketing-Cloud (vormals Pardot) hat extra Authentication-Flow.",
        spf_guide="include:_spf.salesforce.com (Sales Cloud) oder include:_spf.exacttarget.com (Marketing Cloud / Pardot).",
        dkim_guide="Salesforce Setup → Email Administration → DKIM Keys → Create new key. Public-Key als TXT ins DNS.",
        public_url="https://help.salesforce.com/s/articleView?id=sf.emailadmin_set_up_dkim.htm",
        ptr_patterns=[r"\.salesforce\.com$", r"\.exacttarget\.com$", r"\.pardot\.com$"],
    ),
    Sender(
        slug="zendesk",
        name="Zendesk",
        category="crm",
        dmarc_capable="configurable",
        description="Support-Ticketing-System. Sendet Ticket-Updates auch im Namen deiner Domain.",
        spf_guide="include:_spf.zendesk.com",
        dkim_guide="Zendesk Admin → Channels → Email → Allowed Sending Domains → DKIM Key Required.",
        public_url="https://support.zendesk.com/hc/en-us/articles/4408886828570",
        ptr_patterns=[r"\.zendesk\.com$"],
    ),
    Sender(
        slug="freshdesk",
        name="Freshdesk",
        category="crm",
        dmarc_capable="configurable",
        description="Helpdesk-Ticketing. Sendet via shared Infrastructure.",
        spf_guide="include:email.freshdesk.com",
        dkim_guide="Freshdesk Admin → Email Settings → DKIM Configuration → CNAME-Records ins DNS.",
        public_url="https://support.freshdesk.com/support/solutions/articles/50000000627",
        ptr_patterns=[r"\.freshdesk\.com$", r"\.freshmail\.com$"],
    ),
    Sender(
        slug="intercom",
        name="Intercom",
        category="crm",
        dmarc_capable="yes",
        description="Customer-Messaging-Plattform. Sendet auch Email-Conversations.",
        spf_guide="include:_spf.intercom.io",
        dkim_guide="Intercom Settings → Channels → Email → Custom DKIM. Selector + CNAME ins DNS.",
        public_url="https://www.intercom.com/help/en/articles/29-set-up-your-custom-dkim-signature",
        ptr_patterns=[r"\.intercom\.io$", r"\.intercom-mail\.com$"],
    ),
    Sender(
        slug="atlassian",
        name="Atlassian (Jira, Confluence)",
        category="crm",
        dmarc_capable="partial",
        description="Jira/Confluence-Notifications. Atlassian sendet im Namen deiner Org-Domain.",
        spf_guide="include:_spf.atlassian.net",
        dkim_guide="Atlassian Admin → Email → DKIM signing — Setup-Anweisungen pro Cloud-Instanz.",
        public_url="https://support.atlassian.com/security-and-access-policies/docs/manage-domain-authentication-for-email/",
        ptr_patterns=[r"\.atlassian\.net$", r"\.atlassian\.com$"],
    ),
    Sender(
        slug="shopify",
        name="Shopify",
        category="crm",
        dmarc_capable="yes",
        description="E-Commerce-Plattform. Sendet Order-Confirmations + Marketing-Mails im Namen des Shops.",
        spf_guide="Shopify ändert seit 2024 zu Sender Authentication via eigener Domain-Configuration.",
        dkim_guide="Shopify Admin → Settings → Notifications → Sender Email → Authenticate. CNAME-Records ins DNS.",
        public_url="https://help.shopify.com/en/manual/orders/notifications/email-sender-authentication",
        ptr_patterns=[r"\.shopify\.com$", r"\.shopifyemail\.com$"],
    ),
    Sender(
        slug="docusign",
        name="DocuSign",
        category="crm",
        dmarc_capable="yes",
        description="Signatur-Service mit eigenen Signing-Emails.",
        spf_guide="include:_spf.docusign.net",
        dkim_guide="DocuSign Admin → Sending Settings → Email Brand. Selector wird vorgegeben.",
        public_url="https://support.docusign.com/s/document-item?language=en_US&bundleId=pik1583277475390",
        ptr_patterns=[r"\.docusign\.net$"],
    ),

    # ===== CH-Spezial =====
    Sender(
        slug="seppmail",
        name="SEPPmail",
        category="ch_special",
        dmarc_capable="yes",
        description="Schweizer Mail-Encryption-Gateway. Wird oft INSIDE der Mail-Infrastruktur eingesetzt.",
        spf_guide="SEPPmail ist normalerweise inline — die Sender-IP bleibt deine eigene. Kein extra SPF nötig.",
        dkim_guide="SEPPmail signiert mit deinem eigenen DKIM-Key wenn entsprechend konfiguriert.",
        public_url="https://seppmail.com",
        notes="Spezialfall: SEPPmail ändert oft das Subject / fügt Banner ein, was DMARC-Alignment auf From-Domain trotzdem beibehalten sollte. Wir helfen bei der Konfiguration.",
        ptr_patterns=[r"\.seppmail\..*$"],
    ),
    Sender(
        slug="hin-mail",
        name="HIN (Health Info Net)",
        category="ch_special",
        dmarc_capable="yes",
        description="CH-Gesundheitswesen-Mail-Infrastruktur. Bereich Spitäler, Praxen, Apotheken.",
        spf_guide="HIN als Sender ist meist über eigenes SMTP-Routing eingebunden, nicht über SPF inkludiert.",
        dkim_guide="HIN signiert mit deinem DKIM wenn das HIN-Gateway entsprechend konfiguriert ist.",
        public_url="https://www.hin.ch",
        notes="Pflicht-Infrastruktur für FMH-konforme Kommunikation. Wir machen das Setup.",
        ptr_patterns=[r"\.hin\.ch$"],
    ),
]


# ============================================================================
# Public Accessors
# ============================================================================

_BY_SLUG: dict[str, Sender] = {s.slug: s for s in _DB}


def all_senders() -> list[Sender]:
    """Alle Sender, kategorisiert."""
    return _DB


def get_sender(slug: str) -> Optional[Sender]:
    """Sender per Slug-Lookup."""
    return _BY_SLUG.get(slug.lower())


def senders_by_category() -> dict[str, list[Sender]]:
    """Sender gruppiert nach Kategorie."""
    out: dict[str, list[Sender]] = {}
    for s in _DB:
        out.setdefault(s.category, []).append(s)
    for k in out:
        out[k].sort(key=lambda s: s.name.lower())
    return out


CATEGORY_LABELS = {
    "mailbox":       "Mail-Hosting / Mailbox-Provider",
    "marketing":     "Marketing / Newsletter",
    "transactional": "Transactional (API-Mailer)",
    "crm":           "CRM &amp; SaaS-Tools",
    "gateway":       "Mail-Gateway / Security",
    "ch_special":    "Schweizer Spezial-Anbieter",
}

CATEGORY_ICONS = {
    "mailbox":       "📨",
    "marketing":     "📢",
    "transactional": "⚡",
    "crm":           "🤝",
    "gateway":       "🛡️",
    "ch_special":    "🇨🇭",
}

CAPABLE_LABELS = {
    "yes":          ("✓ Voll DMARC-konform", "ok"),
    "configurable": ("⚙️ Konfigurierbar", "warn"),
    "partial":      ("△ Teilweise — Aufwand!", "warn"),
    "no":           ("✕ Nicht DMARC-konform", "bad"),
}
