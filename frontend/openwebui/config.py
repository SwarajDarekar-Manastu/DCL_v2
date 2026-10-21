"""How the Open WebUI functions reach the DCL backend (mirror of frontend/console/src/lib/config.ts).

Values come from each function's admin Valves (stored by Open WebUI), never from code or this repository.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit


class DclConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DclConfig:
    engine_url: str
    shared_secret: str
    console_url: str
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 180.0  # longest gap between two SSE frames (design synthesis p95 is 60 s)


def build_config(engine_url: str, shared_secret: str, console_url: str = "") -> DclConfig:
    """Refuse a partial configuration with a message naming the Valves to fill in."""
    required = (("ENGINE_URL", engine_url), ("ENGINE_SHARED_SECRET", shared_secret))
    missing = [name for name, value in required if not value.strip()]
    if missing:
        raise DclConfigError(f"Manastu engine is not configured: set the {', '.join(missing)} valve(s)")
    for name, url in (("ENGINE_URL", engine_url), ("CONSOLE_URL", console_url)):
        if url and urlsplit(url.strip()).scheme not in ("http", "https"):
            raise DclConfigError(f"{name} must be an http(s) URL")
    return DclConfig(
        engine_url=engine_url.strip().rstrip("/"),
        shared_secret=shared_secret.strip(),
        console_url=console_url.strip().rstrip("/"),
    )
