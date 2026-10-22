import httpx
import pytest

from backend.common import office
from backend.config import Settings

URL = "http://libreoffice.test:2003"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(office, "get_settings", lambda: Settings(_env_file=None, DCL_OFFICE_URL=URL))


class Office:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def test_converts_bytes_through_the_service():
    svc = Office(httpx.Response(200, content=b"%PDF-1.7 converted"))
    assert (
        office.convert(b"docx-bytes", ".DOCX", "pdf", transport=httpx.MockTransport(svc))
        == b"%PDF-1.7 converted"
    )
    request = svc.requests[0]
    assert str(request.url) == f"{URL}/convert?from=docx&to=pdf"
    assert request.content == b"docx-bytes"


def test_same_format_without_recalc_is_returned_untouched():
    svc = Office(httpx.Response(500))
    assert office.convert(b"x", "xlsx", "xlsx", transport=httpx.MockTransport(svc)) == b"x"
    assert svc.requests == []


def test_recalc_round_trips_through_libreoffice():
    svc = Office(httpx.Response(200, content=b"PK fresh"))
    assert (
        office.convert(b"PK stale", "xlsx", "xlsx", recalc=True, transport=httpx.MockTransport(svc))
        == b"PK fresh"
    )
    assert str(svc.requests[0].url).endswith("from=xlsx&to=xlsx")


def test_conversion_failure_is_reported_with_the_service_detail():
    svc = Office(httpx.Response(422, text="soffice produced no .pdf (exit 1): General Error"))
    with pytest.raises(
        office.OfficeConversionError, match=r"\.pptx -> \.pdf \(HTTP 422\): soffice produced no \.pdf"
    ):
        office.convert(b"broken", "pptx", "pdf", transport=httpx.MockTransport(svc))


def test_unsupported_input_is_refused_before_any_call():
    svc = Office(httpx.Response(200, content=b"x"))
    with pytest.raises(office.OfficeConversionError, match="unsupported input format .exe"):
        office.convert(b"x", "exe", "pdf", transport=httpx.MockTransport(svc))
    assert svc.requests == []


def test_connection_error_is_retried_once():
    svc = Office(httpx.ConnectError("refused"), httpx.Response(200, content=b"ok"))
    assert office.convert(b"x", "doc", "docx", transport=httpx.MockTransport(svc)) == b"ok"
    assert len(svc.requests) == 2


def test_unreachable_after_retry_is_reported():
    svc = Office(httpx.ConnectError("refused"))
    with pytest.raises(office.OfficeConversionError, match="unreachable: ConnectError"):
        office.convert(b"x", "doc", "pdf", transport=httpx.MockTransport(svc))
