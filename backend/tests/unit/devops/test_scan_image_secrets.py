import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "devops" / "ci" / "scan_image_secrets.py"
spec = importlib.util.spec_from_file_location("scan_image_secrets", SCRIPT)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

FAKE_GOOGLE_KEY = b"AIza" + b"B" * 35
PRIVATE_KEY = b"-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\n"


def layer(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def saved_image(tmp_path: Path, layers: list[dict[str, bytes]], env: list[str] | None = None) -> Path:
    path = tmp_path / "image.tar"
    config = json.dumps({"config": {"Env": env or ["PATH=/usr/bin", "PYTHON_GPG_KEY=ABC"]}}).encode()
    names = [f"blobs/sha256/layer{i}" for i in range(len(layers))]
    manifest = json.dumps([{"Config": "blobs/sha256/config", "Layers": names}]).encode()
    with tarfile.open(path, "w") as image:
        for name, data in [("manifest.json", manifest), ("blobs/sha256/config", config)] + list(
            zip(names, [layer(files) for files in layers], strict=True)
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            image.addfile(info, io.BytesIO(data))
    return path


def rules(findings) -> set[tuple[str, str]]:
    return {(f.path, f.rule) for f in findings}


def test_clean_image_has_no_findings(tmp_path):
    image = saved_image(
        tmp_path,
        [
            {
                "app/backend/main.py": b"print('ok')",
                "app/.env.example": b"GEMINI_GATEWAY_KEY=\n",
                "etc/ssl/certs/ca.pem": b"-----BEGIN CERTIFICATE-----",
                "opt/venv/lib/python3.12/site-packages/certifi/cacert.pem": b"cert",
                "usr/lib/python3/dist-packages/x.py": PRIVATE_KEY,
                "usr/share/gnupg/sks-keyservers.netCA.pem": b"-----BEGIN CERTIFICATE-----",
            }
        ],
    )
    assert scan.scan_saved_image(image, {}) == []


def test_planted_secrets_are_found_in_any_layer(tmp_path):
    image = saved_image(
        tmp_path,
        [
            {"app/.env": b"X=1"},
            {"home/app/.ssh/id_rsa": b"k", "app/backend/settings.py": b"KEY='" + FAKE_GOOGLE_KEY + b"'"},
            {
                "app/keys/service.pem": PRIVATE_KEY,
                "app/cert.pfx": b"p12",
                "usr/local/share/leaked.pem": PRIVATE_KEY,
            },
        ],
    )
    found = rules(scan.scan_saved_image(image, {}))
    assert ("app/.env", "secret-file:.env") in found
    assert ("home/app/.ssh/id_rsa", "secret-file:id_rsa") in found
    assert ("app/backend/settings.py", "google-api-key") in found
    assert ("app/keys/service.pem", "pem-private-key") in found
    assert ("usr/local/share/leaked.pem", "pem-private-key") in found
    assert ("app/cert.pfx", "secret-file:*.pfx") in found


def test_secret_like_env_in_image_config_is_a_finding(tmp_path):
    image = saved_image(
        tmp_path, [{"app/a.py": b""}], env=["PATH=/x", "GEMINI_GATEWAY_KEY=abc", "PYTHON_GPG_KEY=1"]
    )
    assert rules(scan.scan_saved_image(image, {})) == {("ENV GEMINI_GATEWAY_KEY", "secret-like-env-in-image")}


def test_exact_env_values_are_found_anywhere_and_never_printed(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DCL_DB_PASSWORD=s3cr3t-db-password\nDCL_TENANT_ID=not-a-secret-but-long\nSHORT_KEY=abc\n"
    )
    values = scan.secret_values(env_file)
    assert set(values) == {"DCL_DB_PASSWORD"}
    image = saved_image(tmp_path, [{"usr/lib/leak.conf": b"password=s3cr3t-db-password"}])
    findings = scan.scan_saved_image(image, values)
    assert rules(findings) == {("usr/lib/leak.conf", "env-value:DCL_DB_PASSWORD")}
    assert "s3cr3t" not in str(findings[0])


@pytest.mark.parametrize("name", [".env", ".env.production", "x.key", "bundle.p12", "id_ed25519"])
def test_secret_file_names(name):
    assert scan.secret_file_rule(f"app/{name}") is not None


def test_env_example_is_allowed():
    assert scan.secret_file_rule("app/.env.example") is None
