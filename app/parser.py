"""DMARC aggregate report parsing.

Reports follow the schema from RFC 7489 (and Google/MS variants). They arrive as:
- raw XML
- gzip-compressed XML (.gz)
- zip archives containing one or more XML files (.zip)
"""
from __future__ import annotations

import gzip
import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from defusedxml import ElementTree as ET


@dataclass
class ParsedAuthResult:
    auth_type: str
    domain: Optional[str] = None
    selector: Optional[str] = None
    result: Optional[str] = None
    scope: Optional[str] = None


@dataclass
class ParsedRecord:
    source_ip: str
    count: int
    disposition: Optional[str] = None
    dkim_eval: Optional[str] = None
    spf_eval: Optional[str] = None
    reason_type: Optional[str] = None
    reason_comment: Optional[str] = None
    header_from: Optional[str] = None
    envelope_from: Optional[str] = None
    envelope_to: Optional[str] = None
    auth_results: list[ParsedAuthResult] = field(default_factory=list)


@dataclass
class ParsedReport:
    org_name: str
    org_email: str
    org_extra_contact: Optional[str]
    external_report_id: str
    date_begin: datetime
    date_end: datetime
    policy_domain: str
    policy_adkim: Optional[str] = None
    policy_aspf: Optional[str] = None
    policy_p: Optional[str] = None
    policy_sp: Optional[str] = None
    policy_pct: Optional[int] = None
    policy_fo: Optional[str] = None
    records: list[ParsedRecord] = field(default_factory=list)
    raw_xml: Optional[str] = None


class DmarcParseError(ValueError):
    pass


def _text(node, path: str) -> Optional[str]:
    if node is None:
        return None
    found = node.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _int(node, path: str) -> Optional[int]:
    val = _text(node, path)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _epoch_to_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def parse_xml(xml_bytes: bytes) -> ParsedReport:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise DmarcParseError(f"Invalid XML: {e}") from e

    if root.tag.endswith("}feedback"):
        # strip namespace once for predictable .find()
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

    if root.tag != "feedback":
        raise DmarcParseError(f"Unexpected root element: {root.tag!r}")

    meta = root.find("report_metadata")
    policy = root.find("policy_published")

    if meta is None or policy is None:
        raise DmarcParseError("Missing report_metadata or policy_published")

    date_range = meta.find("date_range")
    begin = _epoch_to_dt(_text(date_range, "begin"))
    end = _epoch_to_dt(_text(date_range, "end"))
    if begin is None or end is None:
        raise DmarcParseError("Missing date_range/begin or date_range/end")

    org_name = _text(meta, "org_name") or "unknown"
    org_email = _text(meta, "email") or "unknown@unknown"
    extra_contact = _text(meta, "extra_contact_info")
    external_id = _text(meta, "report_id") or f"{org_email}-{int(begin.timestamp())}"

    parsed = ParsedReport(
        org_name=org_name,
        org_email=org_email,
        org_extra_contact=extra_contact,
        external_report_id=external_id,
        date_begin=begin,
        date_end=end,
        policy_domain=_text(policy, "domain") or "",
        policy_adkim=_text(policy, "adkim"),
        policy_aspf=_text(policy, "aspf"),
        policy_p=_text(policy, "p"),
        policy_sp=_text(policy, "sp"),
        policy_pct=_int(policy, "pct"),
        policy_fo=_text(policy, "fo"),
    )

    for rec in root.findall("record"):
        row = rec.find("row")
        if row is None:
            continue
        identifiers = rec.find("identifiers")
        policy_eval = row.find("policy_evaluated")
        reason = policy_eval.find("reason") if policy_eval is not None else None

        pr = ParsedRecord(
            source_ip=_text(row, "source_ip") or "",
            count=_int(row, "count") or 0,
            disposition=_text(policy_eval, "disposition"),
            dkim_eval=_text(policy_eval, "dkim"),
            spf_eval=_text(policy_eval, "spf"),
            reason_type=_text(reason, "type") if reason is not None else None,
            reason_comment=_text(reason, "comment") if reason is not None else None,
            header_from=_text(identifiers, "header_from"),
            envelope_from=_text(identifiers, "envelope_from"),
            envelope_to=_text(identifiers, "envelope_to"),
        )

        auth = rec.find("auth_results")
        if auth is not None:
            for dkim in auth.findall("dkim"):
                pr.auth_results.append(
                    ParsedAuthResult(
                        auth_type="dkim",
                        domain=_text(dkim, "domain"),
                        selector=_text(dkim, "selector"),
                        result=_text(dkim, "result"),
                    )
                )
            for spf in auth.findall("spf"):
                pr.auth_results.append(
                    ParsedAuthResult(
                        auth_type="spf",
                        domain=_text(spf, "domain"),
                        result=_text(spf, "result"),
                        scope=_text(spf, "scope"),
                    )
                )

        if not pr.source_ip:
            continue
        parsed.records.append(pr)

    parsed.raw_xml = xml_bytes.decode("utf-8", errors="replace")
    return parsed


def extract_xml_payloads(filename: str, data: bytes) -> Iterable[tuple[str, bytes]]:
    """Yield (inner_filename, xml_bytes) tuples from a possibly-compressed payload."""
    name = (filename or "").lower()

    # zip
    if name.endswith(".zip") or data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    inner = info.filename
                    with zf.open(info) as fh:
                        payload = fh.read()
                    if inner.lower().endswith(".gz"):
                        try:
                            payload = gzip.decompress(payload)
                            inner = inner[:-3]
                        except OSError:
                            pass
                    yield inner, payload
            return
        except zipfile.BadZipFile:
            pass

    # gzip
    if name.endswith(".gz") or data[:2] == b"\x1f\x8b":
        try:
            yield name[:-3] if name.endswith(".gz") else name, gzip.decompress(data)
            return
        except OSError:
            pass

    # raw xml
    yield filename or "report.xml", data


def parse_payload(filename: str, data: bytes) -> list[ParsedReport]:
    out: list[ParsedReport] = []
    errors: list[str] = []
    for inner, xml_bytes in extract_xml_payloads(filename, data):
        try:
            out.append(parse_xml(xml_bytes))
        except DmarcParseError as e:
            errors.append(f"{inner}: {e}")
    if not out and errors:
        raise DmarcParseError("; ".join(errors))
    return out
