"""Compare the application source of the working tree with what every running compose service holds.

``python backend/devops/ci/verify_workers.py [project]`` (default ``dcl-v2``) hashes every
``backend/**/*.py`` outside ``tests`` and ``devops`` and compares it, per file, with the same files inside
each running service. It exits 1 on any difference. A health check stays green on an image built before the
last edit, so run this before testing a deployment.
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKIPPED = ("tests", "devops", "__pycache__")


def local_hashes() -> dict[str, str]:
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / "backend").rglob("*.py"))
        if not any(part in SKIPPED for part in p.relative_to(ROOT / "backend").parts)
    }


DOCKER = shutil.which("docker") or "docker"


def docker(*args: str) -> str:
    # The arguments are constants and the compose project name given on this command line.
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, check=False).stdout  # noqa: S603


def container_hashes(name: str) -> dict[str, str] | None:
    script = (
        "cd /app 2>/dev/null && find backend -name '*.py' -not -path '*/tests/*' -not -path '*/devops/*' "
        "-not -path '*/__pycache__/*' | xargs sha256sum"
    )
    out = docker("exec", name, "sh", "-c", script)
    rows = [line.split("  ", 1) for line in out.splitlines() if "  " in line]
    return {path: digest for digest, path in rows} or None


def main(project: str = "dcl-v2") -> int:
    tree = local_hashes()
    names = docker("ps", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Names}}")
    failed = False
    for name in sorted(names.split()):
        held = container_hashes(name)
        if held is None:
            continue  # not an application container
        different = sorted(p for p, digest in tree.items() if held.get(p) != digest)
        extra = sorted(set(held) - set(tree))
        failed = failed or bool(different or extra)
        verdict = (
            "current"
            if not (different or extra)
            else f"STALE: {len(different)} different, {len(extra)} extra"
        )
        print(f"{name:34s} {len(held):4d} files  {verdict}")
        for path in (different + extra)[:5]:
            print(f"    {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
