"""Secret scan of every layer of a Docker image (docs/architecture/01 §7.1: secrets never enter an image).

    python backend/devops/ci/scan_image_secrets.py dcl-v2-backend:local [--forbid-values-from .env]

Fails (exit 1) when any layer holds a file that carries secrets (`.env`, `.key`, PKCS#12 bundles, SSH keys,
or a `.pem`/`.crt`/`.cer` that contains a private key; public certificates are fine), when the application
directories hold key-shaped content (PEM private keys, Google `AIza` keys), when the image config sets an
environment variable whose name looks like a secret, or, with --forbid-values-from, when any file in the image
contains one of that env file's secret values. Findings name the file and the rule or the variable, never the
matching value.
"""

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SECRET_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "*.key",
    "*.pfx",
    "*.p12",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519*",
)
KEY_CONTAINERS = ("*.pem", "*.crt", "*.cer")
ALLOWED_FILES = (".env.example",)
PUBLIC_CERT_DIRS = (
    "etc/ssl/",
    "usr/share/ca-certificates/",
    "usr/lib/ssl/",
    "/certifi/",
    "/pip/_vendor/certifi/",
)
CONTENT_DIRS = ("app/", "home/", "root/", "opt/dcl/")
CONTENT_RULES = {
    "pem-private-key": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "google-api-key": re.compile(rb"AIza[0-9A-Za-z_\-]{35}"),
}
SECRET_ENV_NAME = re.compile(r"(KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL)", re.IGNORECASE)
NON_SECRET_ENV = frozenset({"GPG_KEY", "PYTHON_GPG_KEY"})
SECRET_VALUE_NAME = re.compile(r"(KEY|SECRET|PASSWORD|TOKEN|THUMBPRINT|WEBHOOK|DATABASE_URL)", re.IGNORECASE)
MIN_VALUE_LENGTH = 8
MAX_SCANNED_FILE = 8 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    layer: str
    path: str
    rule: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.path} (layer {self.layer[:19]})"


def secret_file_rule(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name in ALLOWED_FILES or any(d in f"/{path}" or path.startswith(d) for d in PUBLIC_CERT_DIRS):
        return None
    for pattern in SECRET_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return f"secret-file:{pattern}"
    return None


def scan_layer(layer: str, archive: tarfile.TarFile, values: dict[str, bytes]) -> Iterator[Finding]:
    for member in archive:
        if not member.isfile():
            continue
        path = member.name.removeprefix("./")
        rule = secret_file_rule(path)
        if rule:
            yield Finding(layer, path, rule)
        in_app = path.startswith(CONTENT_DIRS)
        key_container = any(fnmatch.fnmatch(path.rsplit("/", 1)[-1], p) for p in KEY_CONTAINERS)
        if member.size > MAX_SCANNED_FILE or not (in_app or key_container or values):
            continue
        handle = archive.extractfile(member)
        data = handle.read() if handle else b""
        if key_container and not in_app and CONTENT_RULES["pem-private-key"].search(data):
            yield Finding(layer, path, "pem-private-key")
        if in_app:
            for name, pattern in CONTENT_RULES.items():
                if pattern.search(data):
                    yield Finding(layer, path, name)
        for name, value in values.items():
            if value in data:
                yield Finding(layer, path, f"env-value:{name}")


def config_findings(config: dict) -> Iterator[Finding]:
    for entry in (config.get("config") or {}).get("Env") or []:
        name = entry.split("=", 1)[0]
        if name not in NON_SECRET_ENV and SECRET_ENV_NAME.search(name):
            yield Finding("config", f"ENV {name}", "secret-like-env-in-image")


def secret_values(env_file: Path) -> dict[str, bytes]:
    from dotenv import dotenv_values

    return {
        name: value.encode()
        for name, value in dotenv_values(env_file).items()
        if value and len(value) >= MIN_VALUE_LENGTH and SECRET_VALUE_NAME.search(name)
    }


def scan_saved_image(tar_path: Path, values: dict[str, bytes]) -> list[Finding]:
    findings: list[Finding] = []
    with tarfile.open(tar_path) as image:
        manifest = json.load(image.extractfile("manifest.json"))[0]
        findings += config_findings(json.load(image.extractfile(manifest["Config"])))
        for layer in manifest["Layers"]:
            with tarfile.open(fileobj=image.extractfile(layer), mode="r:*") as archive:
                findings += scan_layer(layer, archive, values)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image")
    parser.add_argument(
        "--forbid-values-from", type=Path, help="env file whose secret values must not appear"
    )
    args = parser.parse_args(argv)
    values = secret_values(args.forbid_values_from) if args.forbid_values_from else {}
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "image.tar"
        with tar_path.open("wb") as out:
            subprocess.run(["docker", "save", args.image], stdout=out, check=True)  # noqa: S603, S607
        findings = scan_saved_image(tar_path, values)
    for finding in findings:
        print(f"FINDING {finding}")
    checked = f"{len(values)} env values" if values else "patterns only"
    print(f"image secret scan of {args.image}: {len(findings)} finding(s), {checked}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
