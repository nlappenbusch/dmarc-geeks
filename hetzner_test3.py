from app.hetzner_dns import HetznerDNS
from app.config import get_settings
s = get_settings()
print("Hetzner upsert smoke test:")
with HetznerDNS(s.hetzner_dns_token) as cli:
    # Create
    out = cli.upsert_record(s.hetzner_dns_zone, "test-upsert._report._dmarc", "TXT", "v=DMARC1")
    vals = [r.get("value") for r in out.get("records", [])]
    print(f"  CREATE: name={out.get('name')!r} value={vals}")
    # Update (same name, different value)
    out = cli.upsert_record(s.hetzner_dns_zone, "test-upsert._report._dmarc", "TXT", "v=DMARC1; p=quarantine")
    vals = [r.get("value") for r in out.get("records", [])]
    print(f"  UPDATE: name={out.get('name')!r} value={vals}")
    # Cleanup
    ok = cli.delete_record_by_name(s.hetzner_dns_zone, "test-upsert._report._dmarc", "TXT")
    print(f"  DELETE: ok={ok}")
print("DONE")
