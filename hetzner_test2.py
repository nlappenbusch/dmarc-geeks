"""Probe the Hetzner Cloud DNS RRSet API to see what body format is expected."""
import httpx
from app.config import get_settings

s = get_settings()
token = s.hetzner_dns_token
zone = s.hetzner_dns_zone

cli = httpx.Client(
    base_url="https://api.hetzner.cloud/v1",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    timeout=10.0,
)

# 1. List existing rrsets — as a model for what the API returns
print("=== Existing TXT rrsets in zone ===")
r = cli.get(f"/zones/{zone}/rrsets", params={"type": "TXT"})
print(f"  {r.status_code}")
for rrset in r.json().get("rrsets", []):
    print(f"  name={rrset.get('name')!r:30s} type={rrset.get('type')} ttl={rrset.get('ttl')}")
    print(f"    records: {rrset.get('records')}")

# 2. Try PUT to create new rrset (variant 1: minimal body)
print("\n=== PUT variant 1 (minimal body) ===")
body = {
    "name": "test-probe._report._dmarc",
    "type": "TXT",
    "ttl": 3600,
    "records": [{"value": '"v=DMARC1"'}],
}
r = cli.put(f"/zones/{zone}/rrsets/test-probe._report._dmarc/TXT", json=body)
print(f"  status={r.status_code}")
print(f"  body={r.text[:400]}")

# 3. Try POST to /rrsets (creation variant)
print("\n=== POST /rrsets variant ===")
body2 = {
    "name": "test-probe2._report._dmarc",
    "type": "TXT",
    "ttl": 3600,
    "records": [{"value": '"v=DMARC1"'}],
}
r = cli.post(f"/zones/{zone}/rrsets", json=body2)
print(f"  status={r.status_code}")
print(f"  body={r.text[:400]}")

# Cleanup if any of those succeeded
for n in ("test-probe._report._dmarc", "test-probe2._report._dmarc"):
    cli.delete(f"/zones/{zone}/rrsets/{n}/TXT")

cli.close()
