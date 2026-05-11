from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

BigPK = BigInteger().with_variant(Integer, "sqlite")
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Reseller(Base):
    """Multi-level tenancy: a Reseller (= MSP) owns multiple Tenants (= Endkunden).
    Branding (logo, color, app name) is inherited from Reseller to every Tenant under it.
    """
    __tablename__ = "resellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    is_platform: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # default reseller for direct customers
    custom_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    app_name: Mapped[str] = mapped_column(String(120), default="DMARC Aggregator", nullable=False)
    brand_color: Mapped[str] = mapped_column(String(16), default="#2563eb", nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    support_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), default="agency", nullable=False)  # agency, reseller, reseller_plus
    seat_limit: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    revenue_share_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imprint_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    privacy_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reseller_id: Mapped[Optional[int]] = mapped_column(ForeignKey("resellers.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    domains: Mapped[list["Domain"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    mailboxes: Mapped[list["Mailbox"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    settings: Mapped[Optional["TenantSettings"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", uselist=False, lazy="joined"
    )
    reseller: Mapped[Optional["Reseller"]] = relationship(lazy="joined")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_reseller_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="users")


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_domains_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    verification_token: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # External-Destination-Authorization (RUA-Reports an unsere Mailbox).
    # True = wir haben den Authorization-Record im Hetzner DNS angelegt.
    auth_record_managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auth_record_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # CNAME-Delegation: True = die Kunden-Domain-DMARC-Policy lebt in unserer
    # Hetzner-Zone, der Kunde hat einen CNAME auf uns gesetzt.
    managed_dmarc: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    managed_policy: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # gespeicherte Policy-String
    managed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="domains")
    reports: Mapped[list["Report"]] = relationship(back_populates="domain", cascade="all, delete-orphan")


class Mailbox(Base):
    __tablename__ = "mailboxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    reseller_id: Mapped[Optional[int]] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    folder: Mapped[str] = mapped_column(String(255), default="INBOX", nullable=False)
    move_to_folder: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="mailboxes")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("org_email", "external_report_id", name="uq_reports_org_extid"),
        Index("ix_reports_tenant_date", "tenant_id", "date_begin"),
        Index("ix_reports_domain_date", "domain_id", "date_begin"),
    )

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True)

    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_email: Mapped[str] = mapped_column(String(255), nullable=False)
    org_extra_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_report_id: Mapped[str] = mapped_column(String(255), nullable=False)

    date_begin: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    policy_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_adkim: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    policy_aspf: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    policy_p: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    policy_sp: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    policy_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    policy_fo: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    raw_xml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    domain: Mapped[Domain] = relationship(back_populates="reports")
    records: Mapped[list["Record"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (
        Index("ix_records_report", "report_id"),
        Index("ix_records_source_ip", "source_ip"),
    )

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    source_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    source_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    disposition: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    dkim_eval: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    spf_eval: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    reason_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reason_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    header_from: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    envelope_from: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    envelope_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    report: Mapped[Report] = relationship(back_populates="records")
    auth_results: Mapped[list["AuthResult"]] = relationship(back_populates="record", cascade="all, delete-orphan")


class AuthResult(Base):
    __tablename__ = "auth_results"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), nullable=False, index=True)
    auth_type: Mapped[str] = mapped_column(String(8), nullable=False)  # dkim | spf
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    selector: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    record: Mapped[Record] = relationship(back_populates="auth_results")


class IngestLog(Base):
    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # imap, upload
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # ok, dup, error, ignored
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_id: Mapped[Optional[int]] = mapped_column(BigPK, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TenantSettings(Base):
    """1:1 sidecar table for Tenant. Avoids altering existing tables."""
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    brand_color: Mapped[str] = mapped_column(String(16), default="#2563eb", nullable=False)
    weekly_digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    digest_recipients: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # comma list
    spike_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    spike_threshold_pct: Mapped[int] = mapped_column(Integer, default=10, nullable=False)  # fail-rate %
    spike_min_volume: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    last_digest_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="settings")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # public part, e.g. dmk_abc123
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class IpAllowlist(Base):
    __tablename__ = "ip_allowlist"
    __table_args__ = (UniqueConstraint("domain_id", "ip_or_cidr", name="uq_allowlist_domain_ip"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True)
    ip_or_cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tags_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#64748b", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DomainTag(Base):
    __tablename__ = "domain_tags"

    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    events: Mapped[str] = mapped_column(String(255), default="report.imported", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuthToken(Base):
    """Single-use tokens for password reset, signup confirmation, magic-link login."""
    __tablename__ = "auth_tokens"
    __table_args__ = (Index("ix_auth_tokens_kind_email", "kind", "email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # reset, signup
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CustomerProfile(Base):
    """1:1 sidecar to Tenant — invoice/contact data, used by Tenant-Admin and Superadmin."""
    __tablename__ = "customer_profiles"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    street: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    vat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), default="community", nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class NotificationPreference(Base):
    """Per-user opt-out flags for tenant-scoped notification events.

    Missing row = all defaults (i.e. user receives everything). Row exists once
    user has saved preferences at least once.
    """
    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    blacklist_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    blacklist_resolved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dmarc_spike: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weekly_digest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    new_sender_detected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    domain_added: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quiet_hours_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-23 UTC
    quiet_hours_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-23 UTC
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BlacklistCheck(Base):
    """Result of a DNSBL/RBL probe for a single (domain, ip) pair at a point in time.

    Created once per scheduled run per IP. Diff between runs drives the alert.
    """
    __tablename__ = "blacklist_checks"
    __table_args__ = (
        Index("ix_bl_domain_ip_time", "domain_id", "ip", "checked_at"),
    )

    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    domain_id: Mapped[Optional[int]] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), nullable=True, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="mx")  # mx | sender | manual
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    listed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 clean / 1 info / 2 warn / 3 critical
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    hits_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list[hit]
    # Anti-spam cooldown: when the last notification of a given event-type was
    # actually sent for this (domain, ip). Used to dedupe alerts so flaky
    # DNSBL responses (rate-limits, NXDOMAIN flapping) don't cause loops.
    alerted_event: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    alerted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MailTest(Base):
    """Public mail-tester clone: user gets unique <token>@<our-subdomain>,
    sends a mail to it, we score it 0-10 like mail-tester.com does.

    Public + anonymous by default. If user later enters Email for the detail-
    report, we store it as lead_email -> wandert ueber den Lead-Notify-Flow zu uns.
    """
    __tablename__ = "mail_tests"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True)
    token: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    requester_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Set when mail arrives
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sender_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    sender_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sender_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    subject: Mapped[Optional[str]] = mapped_column(String(998), nullable=True)
    raw_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Score + Breakdown
    score: Mapped[Optional[float]] = mapped_column(nullable=True)  # 0.0 - 10.0
    breakdown_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lead-Capture Gate
    lead_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    lead_email_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
