"""Chat attachments: fetched once with a cap, read as user-provided evidence, never indexed."""

import asyncio

import httpx
import pytest

from backend.llm_engine.engine.tools import Provenance
from backend.llm_engine.engine.tools.attachments import Attached, AttachmentTooLarge, fetch, read_attachment
from backend.llm_engine.gemini_types import GatewayError, GenerateResult, Pdf, Usage


class Client:
    def __init__(self, reply="Table 2: Pc 12.4 bar at T04."):
        self.reply, self.calls = reply, []

    async def generate(self, *, model, messages, context, **options):
        self.calls.append((messages, context, options))
        if isinstance(self.reply, Exception):
            raise self.reply
        return GenerateResult(self.reply, None, (), Usage(1, 1), model, "stop", "r", 1)


def test_fetch_reads_once_and_refuses_more_than_the_cap():
    http = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 100))
    )
    assert fetch("https://minio.test/u", cap=200, http=http) == b"x" * 100
    with pytest.raises(AttachmentTooLarge):
        fetch("https://minio.test/u", cap=50, http=http)


def test_a_text_file_is_used_as_it_is_and_labelled_as_the_users():
    client = Client()
    item = Attached("notes.csv", "text/csv", b"run,pc_bar\nT04,12.4\n")
    result = asyncio.run(read_attachment(client, item, "What was Pc in T04?"))
    assert client.calls == [] and "T04,12.4" in result.display
    [source] = result.provenance
    assert source.provenance is Provenance.USER_PROVIDED and source.label == "notes.csv (your attachment)"
    assert "not indexed" in result.display


def test_a_pdf_goes_to_gemini_with_the_question_and_office_files_are_converted_first():
    client = Client()
    pdf = Attached("report.pdf", "application/pdf", b"%PDF-1.7 ...")
    result = asyncio.run(read_attachment(client, pdf, "What was Pc in T04?", trace_id="t1"))
    [(messages, context, options)] = client.calls
    assert isinstance(messages[1].parts[1], Pdf) and "What was Pc in T04?" in messages[1].parts[0].text
    assert context.purpose == "engine.attachment" and context.prompt_version == "attachment.v1"
    assert "Pc 12.4 bar" in result.display
    converted = []
    docx = Attached(
        "plan.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK"
    )
    asyncio.run(
        read_attachment(
            Client(), docx, "q", convert_office=lambda d, e, t: converted.append((e, t)) or b"%PDF"
        )
    )
    assert converted == [("docx", "pdf")]


def test_a_failed_read_is_a_warning_not_a_failed_answer():
    result = asyncio.run(
        read_attachment(Client(GatewayError("502")), Attached("a.png", "image/png", b"png"), "q")
    )
    assert result.provenance == [] and "could not be read" in result.warnings[0]
    unknown = asyncio.run(
        read_attachment(Client(), Attached("a.bin", "application/octet-stream", b"\x00"), "q")
    )
    assert "unsupported" in unknown.warnings[0]
