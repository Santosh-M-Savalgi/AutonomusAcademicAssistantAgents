"""Streaming PDF validation for the curriculum upload boundary."""

from __future__ import annotations

import hashlib
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO

from fastapi import UploadFile
from pypdf import PdfReader

from apps.api.config import Settings


class UploadValidationError(ValueError):
    """A safe, public-facing upload validation failure."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class ValidatedPDF:
    """Validated temporary PDF stream and metadata needed by persistence."""

    file: BinaryIO
    original_filename: str
    size_bytes: int
    sha256: str
    page_count: int

    def close(self) -> None:
        """Close the temporary upload stream."""

        self.file.close()


def sanitize_filename(filename: str | None) -> str:
    """Retain safe metadata without allowing paths or control characters."""

    normalized = unicodedata.normalize("NFKC", filename or "syllabus.pdf")
    basename = PurePosixPath(normalized.replace("\\", "/")).name
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", basename)
    safe = "".join(character for character in safe if character.isprintable())
    safe = safe.strip(" .")[:255] or "syllabus.pdf"
    if not safe.lower().endswith(".pdf"):
        safe = f"{safe}.pdf"
    return safe


async def validate_pdf_upload(upload: UploadFile, settings: Settings) -> ValidatedPDF:
    """Stream, sniff, parse, and validate one PDF without unbounded memory use."""

    # Ownership transfers to ValidatedPDF on success; callers close it.
    temporary = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115
    digest = hashlib.sha256()
    total = 0
    try:
        while chunk := await upload.read(settings.upload_chunk_size_bytes):
            total += len(chunk)
            if total > settings.max_upload_size_bytes:
                raise UploadValidationError(
                    "UPLOAD_TOO_LARGE",
                    f"PDF uploads must not exceed {settings.max_upload_size_bytes} bytes.",
                    status_code=413,
                )
            digest.update(chunk)
            temporary.write(chunk)

        if total == 0:
            raise UploadValidationError("EMPTY_UPLOAD", "The uploaded file is empty.")

        temporary.seek(0)
        if temporary.read(5) != b"%PDF-":
            raise UploadValidationError("INVALID_FILE_TYPE", "The upload is not a PDF file.")

        temporary.seek(0)
        if _contains_archive_signature(temporary):
            raise UploadValidationError(
                "SUSPICIOUS_ARCHIVE",
                "The PDF contains a suspicious archive signature.",
            )

        temporary.seek(0)
        try:
            reader = PdfReader(temporary, strict=True)
            if reader.is_encrypted:
                raise UploadValidationError("ENCRYPTED_PDF", "Encrypted PDFs are not accepted.")
            page_count = len(reader.pages)
        except UploadValidationError:
            raise
        except Exception as error:
            raise UploadValidationError("INVALID_PDF", "The PDF could not be read.") from error

        if page_count > settings.max_pdf_pages:
            raise UploadValidationError(
                "PAGE_LIMIT_EXCEEDED",
                f"PDFs must not exceed {settings.max_pdf_pages} pages.",
            )

        temporary.seek(0)
        if _contains_active_content_marker(temporary):
            raise UploadValidationError(
                "UNSAFE_PDF_CONTENT",
                "PDFs containing executable or embedded content are not accepted.",
            )

        temporary.seek(0)
        return ValidatedPDF(
            file=temporary,
            original_filename=sanitize_filename(upload.filename),
            size_bytes=total,
            sha256=digest.hexdigest(),
            page_count=page_count,
        )
    except Exception:
        temporary.close()
        raise


def _contains_archive_signature(file: BinaryIO) -> bool:
    """Detect common embedded archive signatures while scanning bounded bytes."""

    signatures = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08", b"Rar!", b"7z\xbc\xaf\x27\x1c")
    previous = b""
    while chunk := file.read(1024 * 1024):
        data = previous + chunk
        if any(signature in data for signature in signatures):
            return True
        previous = data[-8:]
    return False


def _contains_active_content_marker(file: BinaryIO) -> bool:
    """Reject detectable PDF actions, scripts, attachments, and rich media."""

    markers = (
        b"/JavaScript",
        b"/JS",
        b"/Launch",
        b"/EmbeddedFile",
        b"/FileAttachment",
        b"/RichMedia",
        b"/XFA",
    )
    previous = b""
    while chunk := file.read(1024 * 1024):
        data = previous + chunk
        if any(marker in data for marker in markers):
            return True
        previous = data[-32:]
    return False
