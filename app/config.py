from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(default="sqlite:///./dmarc.db", alias="DATABASE_URL")
    secret_key: str = Field(default="dev-secret-change-me", alias="SECRET_KEY")
    fernet_key: str = Field(default="", alias="FERNET_KEY")

    # Empty-string env values fall back to the field default rather than
    # crashing downstream (e.g. SQLAlchemy can't parse "" as a URL, base_url
    # gets stitched into "/path" and links break).
    @field_validator("database_url", "secret_key", "base_url", mode="before")
    @classmethod
    def _empty_string_falls_back_to_default(cls, v, info):
        if isinstance(v, str) and not v.strip():
            return cls.model_fields[info.field_name].default
        return v

    superadmin_email: str = Field(default="admin@example.com", alias="SUPERADMIN_EMAIL")
    superadmin_password: str = Field(default="changeme", alias="SUPERADMIN_PASSWORD")
    default_tenant_name: str = Field(default="Default", alias="DEFAULT_TENANT_NAME")

    imap_poll_interval_minutes: int = Field(default=15, alias="IMAP_POLL_INTERVAL_MINUTES")
    resolve_ptr: bool = Field(default=True, alias="RESOLVE_PTR")

    session_cookie_name: str = "dmarc_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 14  # 14 days

    # SMTP (optional — features that need email degrade gracefully if unset)
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_tls_verify: bool = Field(default=True, alias="SMTP_TLS_VERIFY")
    smtp_from: str = Field(default="dmarc-aggregator@localhost", alias="SMTP_FROM")

    base_url: str = Field(default="http://localhost:8000", alias="BASE_URL")
    allow_signup: bool = Field(default=True, alias="ALLOW_SIGNUP")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    trusted_proxies: bool = Field(default=False, alias="TRUSTED_PROXIES")

    # Spamhaus DQS (Data Query Service) — empfohlen, kostenlos für non-commercial.
    # Ohne Key fallen wir auf die rate-limited Public-Zonen (zen.spamhaus.org) zurück.
    spamhaus_dqs_key: str = Field(default="", alias="SPAMHAUS_DQS_KEY")
    # Anti-Flapping: nur als "gelistet" werten wenn N aufeinander folgende Checks
    # die gleiche Listung zeigen. 1 = sofort (alt), 2 = stable.
    dnsbl_stability_threshold: int = Field(default=2, alias="DNSBL_STABILITY_THRESHOLD")

    # Hetzner DNS API — aktiviert "DMARC-as-a-Service" Features:
    # - Auto-Authorization-Records für External-Destination-Reports
    # - CNAME-Delegation: Kunde setzt einen CNAME, wir managen die Policy
    hetzner_dns_token: str = Field(default="", alias="HETZNER_DNS_TOKEN")
    # Die Zone in der wir Authorization-Records + Managed-DMARC-Policies hosten.
    # Beispiel: "dmarc-geeks.ch". Die Zone muss bereits in Hetzner DNS existieren.
    hetzner_dns_zone: str = Field(default="", alias="HETZNER_DNS_ZONE")

    # Debug: bei 500ern den vollen Stacktrace im Browser zeigen statt nur die
    # generische Fehler-Seite. NICHT in Produktion anlassen — gibt internals preis.
    debug_traceback: bool = Field(default=False, alias="DEBUG_TRACEBACK")

    # Zusaetzliche Empfaenger fuer Lead-Mails (Kontakt-Anfrage, Domain-Check
    # in oeffentlichen Tools). Komma-separiert. Default leer — nur Operator
    # (SMTP_FROM) bekommt dann was. Auf Prod z.B. private Gmail eintragen.
    lead_notify_emails: str = Field(default="", alias="LEAD_NOTIFY_EMAILS")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
