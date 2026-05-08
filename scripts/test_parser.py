"""Quick sanity test for the parser. Run: python -m scripts.test_parser"""
from pathlib import Path

from app.parser import parse_payload


def main() -> None:
    sample = Path(__file__).parent / "sample_report.xml"
    data = sample.read_bytes()
    reports = parse_payload(sample.name, data)
    assert len(reports) == 1, reports
    rep = reports[0]
    assert rep.policy_domain == "example.com"
    assert len(rep.records) == 2
    assert rep.records[0].count == 42
    assert rep.records[0].dkim_eval == "pass"
    assert rep.records[1].disposition == "quarantine"
    print("OK: parser works.")
    print(f"  org={rep.org_name} reporter={rep.org_email}")
    print(f"  domain={rep.policy_domain} window={rep.date_begin} – {rep.date_end}")
    print(f"  records={len(rep.records)}")


if __name__ == "__main__":
    main()
