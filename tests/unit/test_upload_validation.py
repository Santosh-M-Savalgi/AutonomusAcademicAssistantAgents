"""Unit tests for the streaming PDF upload boundary."""

from io import BytesIO

import pytest
from fastapi import UploadFile
from pypdf import PdfWriter

from apps.api.config import Settings
from apps.api.documents.validation import UploadValidationError, validate_pdf_upload


def make_pdf(page_count: int = 1, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def upload(
    data: bytes, filename: str = "syllabus.pdf", content_type: str = "text/plain"
) -> UploadFile:
    return UploadFile(file=BytesIO(data), filename=filename, headers={"content-type": content_type})


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


async def test_valid_pdf_is_streamed_and_metadata_is_returned() -> None:
    validated = await validate_pdf_upload(
        upload(make_pdf(), "../../Student Syllabus!.pdf"), settings()
    )
    try:
        assert validated.page_count == 1
        assert validated.size_bytes > 0
        assert len(validated.sha256) == 64
        assert validated.original_filename == "Student Syllabus_.pdf"
        assert validated.file.read(5) == b"%PDF-"
    finally:
        validated.close()


@pytest.mark.parametrize(
    ("data", "filename", "code"),
    [
        (b"not a PDF", "syllabus.pdf", "INVALID_FILE_TYPE"),
        (b"%PDF-1.7\nmalformed", "syllabus.pdf", "INVALID_PDF"),
        (b"%PDF-1.7\nPK\x03\x04", "syllabus.pdf", "SUSPICIOUS_ARCHIVE"),
    ],
)
async def test_invalid_or_suspicious_pdf_is_rejected(
    data: bytes, filename: str, code: str
) -> None:
    with pytest.raises(UploadValidationError) as error:
        await validate_pdf_upload(upload(data, filename), settings())
    assert error.value.code == code


async def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(UploadValidationError) as error:
        await validate_pdf_upload(upload(make_pdf(encrypted=True)), settings())
    assert error.value.code == "ENCRYPTED_PDF"


async def test_page_limit_is_enforced() -> None:
    with pytest.raises(UploadValidationError) as error:
        await validate_pdf_upload(upload(make_pdf(2)), settings(max_pdf_pages=1))
    assert error.value.code == "PAGE_LIMIT_EXCEEDED"


async def test_size_limit_is_enforced_before_pdf_parsing() -> None:
    with pytest.raises(UploadValidationError) as error:
        await validate_pdf_upload(upload(make_pdf()), settings(max_upload_size_bytes=10))
    assert error.value.code == "UPLOAD_TOO_LARGE"
