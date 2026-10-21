"""LibreOffice conversions for every route (docs/architecture/01 §5.3): one client, one container.

    from backend.common.office import convert
    pdf = convert(docx_bytes, "docx", "pdf")
    xlsx = convert(xls_bytes, "xls", "xlsx")
    fresh = convert(xlsx_bytes, "xlsx", "xlsx", recalc=True)

The `libreoffice` container (backend/devops/docker/office_server.py) runs one soffice process per request
with a profile that recalculates every formula on load, so a round trip with recalc=True returns a workbook
whose cached values are current. One retry on a connection error or timeout.
"""

import logging
from typing import Literal

import httpx

from backend.config import Group, get_settings

log = logging.getLogger(__name__)

Target = Literal["pdf", "docx", "pptx", "xlsx"]
SUPPORTED_INPUTS = frozenset({"doc", "docx", "rtf", "odt", "ppt", "pptx", "odp", "xls", "xlsx", "ods"})
DEFAULT_TIMEOUT_S = 200.0


class OfficeConversionError(RuntimeError):
    pass


def convert(
    data: bytes,
    from_ext: str,
    to: Target,
    *,
    recalc: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    transport: httpx.BaseTransport | None = None,
) -> bytes:
    ext = from_ext.lower().lstrip(".")
    if ext not in SUPPORTED_INPUTS:
        raise OfficeConversionError(f"unsupported input format .{ext}")
    if ext == to and not recalc:
        return data
    url = str(get_settings().require(Group.OFFICE).office_url).rstrip("/")
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=timeout_s, transport=transport) as http:
                response = http.post(f"{url}/convert", params={"from": ext, "to": to}, content=data)
        except httpx.TransportError as exc:
            if attempt == 2:
                raise OfficeConversionError(f"libreoffice unreachable: {type(exc).__name__}") from exc
            log.warning("libreoffice .%s -> .%s failed (%s); retrying once", ext, to, type(exc).__name__)
            continue
        if response.status_code != 200:
            detail = response.text.strip()[:300]
            raise OfficeConversionError(
                f"libreoffice could not convert .{ext} -> .{to} (HTTP {response.status_code}): {detail}"
            )
        if not response.content:
            raise OfficeConversionError(f"libreoffice returned no data for .{ext} -> .{to}")
        return response.content
    raise AssertionError("unreachable")
