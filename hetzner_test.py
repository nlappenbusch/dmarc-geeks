from app.hetzner_dns import HetznerDNS, delegation_target_fqdn, authorization_record_name
from app.config import get_settings

s = get_settings()
print(f'Token gesetzt: {bool(s.hetzner_dns_token)}')
print(f'Zone:          {s.hetzner_dns_zone}')
print()
print('Live API-Call: list zones (Hetzner Cloud DNS Beta)...')
try:
    with HetznerDNS(s.hetzner_dns_token) as cli:
        zones = cli.list_zones()
        print(f'  -> {len(zones)} zones found')
        for z in zones[:5]:
            print(f'    - {z.get("name")} (id={z.get("id")}, mode={z.get("mode")})')
        target = cli.find_zone(s.hetzner_dns_zone)
        if target:
            print(f'  -> Zone {s.hetzner_dns_zone} found, id={target.get("id")}')
            recs = cli.list_rrsets(s.hetzner_dns_zone, type_filter="TXT")
            print(f'  -> {len(recs)} TXT rrsets in zone')
            for r in recs[:5]:
                vals = [v.get("value", "")[:60] for v in r.get("records", [])]
                ttl = r.get("ttl") or 0
                print(f'    {r.get("name", "")[:40]:40s} ttl={ttl:5d} -> {vals}')
        else:
            print(f'  !! Zone {s.hetzner_dns_zone} NOT found in your account')
except Exception as e:
    print(f'  X Error: {e}')
