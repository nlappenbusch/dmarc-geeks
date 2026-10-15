"""DNSBL return-code handling. Run: python -m scripts.test_blacklist

Regression for the false "KRITISCH: 52.101.103.143 blacklisted" alarm
(2026-10-14): Spamhaus answers 127.255.255.254 to queries via public
resolvers — that must never count as a listing.
"""
import dns.resolver

from app import blacklist


class FakeResolver:
    """Answers every A query with fixed codes; the test point with `probe`."""

    def __init__(self, codes, probe=("127.0.0.2",)):
        self.codes = codes
        self.probe = probe
        self.queries = []

    def resolve(self, qname, rdtype="A", lifetime=None):
        self.queries.append((qname, rdtype))
        if rdtype == "TXT":
            raise dns.resolver.NoAnswer()
        codes = self.probe if qname.startswith("2.0.0.127.") else self.codes
        if codes is None:
            raise dns.resolver.NXDOMAIN()
        return list(codes)


ZEN = [("zen.spamhaus.org", "Spamhaus ZEN", 3)]
OTHER = [("bl.example.net", "Example BL", 2)]
IP = "52.101.103.143"


def run(resolvers, lists):
    blacklist._RESOLVERS[:] = resolvers
    blacklist.cache_clear()
    return blacklist.check_ip(IP, lists)


def main() -> None:
    saved = list(blacklist._RESOLVERS)
    try:
        # Refusal code from Spamhaus → no hit
        assert run([FakeResolver(["127.255.255.254"])], OTHER) == []
        assert run([FakeResolver(["127.255.255.254"], probe=["127.255.255.254"])], ZEN) == []

        # Real listing code → hit
        hits = run([FakeResolver(["127.0.0.2"])], ZEN)
        assert len(hits) == 1 and hits[0]["codes"] == ["127.0.0.2"], hits
        hits = run([FakeResolver(["127.0.0.2"])], OTHER)
        assert len(hits) == 1, hits

        # Refusing resolver is skipped, next resolver gives the real answer
        hits = run([FakeResolver(["127.255.255.254"]), FakeResolver(["127.0.0.2"])], OTHER)
        assert len(hits) == 1, hits

        # Spamhaus: resolver failing the test point (Google: NXDOMAIN, or
        # refusal) is never asked for the real IP — no false clean either.
        blocked = FakeResolver(None, probe=None)
        good = FakeResolver(["127.0.0.2"])
        hits = run([blocked, good], ZEN)
        assert len(hits) == 1, hits
        assert all(q[0].startswith("2.0.0.127.") for q in blocked.queries), blocked.queries

        # All resolvers blocked → zone skipped and nothing cached as clean
        assert run([FakeResolver(None, probe=["127.255.255.254"])], ZEN) == []
        assert ("zen.spamhaus.org", IP) not in blacklist._CACHE

        # Not listed via trustworthy resolver → clean, cached
        assert run([FakeResolver(None)], ZEN) == []
        assert blacklist._CACHE[("zen.spamhaus.org", IP)][1] is None
    finally:
        blacklist._RESOLVERS[:] = saved
        blacklist.cache_clear()
    print("OK: blacklist return codes handled.")


if __name__ == "__main__":
    main()
