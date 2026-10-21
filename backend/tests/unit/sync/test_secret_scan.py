"""Tier 4 secret scan. Fake secrets are assembled at runtime so no secret-shaped literal sits in the repo."""

import pytest

from backend.postgres.enums import DriveItemStatus
from backend.sync.gate import SECRET_VERDICT, scan_secrets, should_scan

AWS = "AKIA" + "Q7" * 8
GOOGLE = "AI" + "za" + "S" * 35
GITHUB = "gh" + "p_" + "a1B2" * 9
SLACK = "xo" + "xb-" + "1234567890-abcdefghij"
JWT = "ey" + "J" + "h" * 12 + ".ey" + "J" + "p" * 12 + "." + "s" * 16
BEARER = "Q" * 32
DB_PASSWORD = "s3cr3t-" + "Value9"
AZURE = "A" * 40 + "=="
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"

CASES = [
    ("aws_access_key_id", f"aws_key_id = {AWS}", AWS),
    ("google_api_key", f'"key": "{GOOGLE}"', GOOGLE),
    ("github_token", f"token: {GITHUB}", GITHUB),
    ("slack_token", f"SLACK={SLACK}", SLACK),
    ("jwt", f"cookie {JWT}", JWT),
    ("bearer_token", f"Authorization: Bearer {BEARER}", BEARER),
    ("connection_string", f"DB=postgresql+psycopg://dcl:{DB_PASSWORD}@db:5432/dcl", DB_PASSWORD),
    ("azure_key", f"DefaultEndpointsProtocol=https;AccountKey={AZURE};", AZURE),
    ("assigned_secret", 'PASSWORD = "Tr1cky-Pass-42"', "Tr1cky-Pass-42"),
    ("private_key", PRIVATE_KEY, None),
]


@pytest.mark.parametrize(("pattern", "line", "secret"), CASES, ids=[c[0] for c in CASES])
def test_each_pattern_is_found_on_its_line_and_the_preview_hides_the_secret(pattern, line, secret):
    hits = scan_secrets(f"# channel map\nAIN0 = pt_101\n{line}\n")
    assert [(h.pattern, h.line) for h in hits] == [(pattern, 3)]
    assert "[REDACTED]" in hits[0].redacted_preview
    if secret is not None:
        assert secret not in hits[0].redacted_preview
        assert secret[:4] in hits[0].redacted_preview


@pytest.mark.parametrize(
    "line",
    [
        'password = "changeme"',
        'api_key = "<your-key>"',
        'secret = "${DCL_SECRET}"',
        'token = "xxxxxxxxxx"',
        "password = getpass.getpass()",
        "url = postgresql://localhost/dcl",
        "Bearer token handling is described in section 3",
        "AIN0 scale = 50 * v - 25",
    ],
)
def test_placeholders_and_ordinary_text_are_not_secrets(line):
    assert scan_secrets(line) == []


def test_secret_verdict_quarantines():
    assert (SECRET_VERDICT.status, SECRET_VERDICT.gate_reason) == (DriveItemStatus.QUARANTINED, "T4:secret")


@pytest.mark.parametrize(
    ("name", "scanned"),
    [
        ("T01.cfg", True),
        ("notes.txt", True),
        ("nozzle_calc.py", True),
        ("objectives.json", True),
        ("setup.ini", True),
        (".env", True),
        (".env.local", True),
        ("run_test.BAT", True),
        ("README.md", True),
        ("TP07_T01.dat", False),
        ("report.pdf", False),
        ("photo.png", False),
    ],
)
def test_which_files_are_scanned(name, scanned):
    assert should_scan(name) is scanned
