"""Page-at-a-time pypdf extraction; no storage, database, HTTP or orchestration."""

import re
from typing import BinaryIO

from pypdf import PdfReader

from packages.curriculum.structure import detect_structure
from packages.domain.extraction import (
    DocumentSource,
    ExtractedPage,
    ExtractionResult,
    ExtractionSummary,
    ExtractionWarning,
    WarningCode,
)
from packages.domain.jobs import JobErrorCode


class ExtractionError(Exception):
    def __init__(self, code: JobErrorCode):
        self.code = code
        super().__init__(code.value)


def normalize_text(text: str) -> str:
    """Keep lines, indentation, bullets and column gaps; never concatenate lines."""

    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = []
    for line in text.split("\n"):
        line = line.expandtabs(4).rstrip()
        # Preserve indentation and table-like gaps as two spaces, ordinary spacing as one.
        indent = len(line) - len(line.lstrip(" "))
        lines.append(" " * min(indent, 16) + re.sub(r" {2,}", "  ", line[indent:]))
    return "\n".join(lines).strip("\n")


def extract_pdf(
    stream: BinaryIO, source: DocumentSource, *, max_bytes: int, max_pages: int,
    max_output_bytes: int, minimum_useful_characters: int,
) -> ExtractionResult:
    stream.seek(0, 2)
    if stream.tell() > max_bytes:
        raise ExtractionError(JobErrorCode.PDF_LIMIT_EXCEEDED)
    stream.seek(0)
    if stream.read(5) != b"%PDF-":
        raise ExtractionError(JobErrorCode.INVALID_PDF)
    stream.seek(0)
    pages: list[ExtractedPage] = []
    warnings: list[ExtractionWarning] = []
    total = 0
    try:
        reader = PdfReader(stream, strict=True)
        if reader.is_encrypted:
            raise ExtractionError(JobErrorCode.ENCRYPTED_PDF)
        if len(reader.pages) > max_pages:
            raise ExtractionError(JobErrorCode.PDF_LIMIT_EXCEEDED)
        if len(reader.pages) != source.page_count:
            raise ExtractionError(JobErrorCode.SOURCE_MISMATCH)
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if total + len(text) > max_output_bytes:
                raise ExtractionError(JobErrorCode.EXTRACTION_OUTPUT_LIMIT)
            text = normalize_text(text)
            total += len(text)
            empty = not text.strip()
            pages.append(ExtractedPage(number=number, text=text,
                                       status="OCR_CANDIDATE" if empty else "TEXT"))
            if empty:
                warnings.append(ExtractionWarning(code=WarningCode.NO_EXTRACTABLE_TEXT,
                                                  page=number))
    except ExtractionError:
        raise
    except MemoryError:
        raise ExtractionError(JobErrorCode.EXTRACTION_RESOURCE_LIMIT) from None
    except Exception:
        raise ExtractionError(JobErrorCode.INVALID_PDF) from None
    useful = sum(sum(not c.isspace() for c in p.text) for p in pages)
    if useful < minimum_useful_characters or not useful:
        warnings.append(ExtractionWarning(code=WarningCode.LOW_TEXT))
    nodes, unclassified, detection_warnings = detect_structure(source, pages)
    warnings.extend(detection_warnings)
    result = ExtractionResult(
        source=source, minimum_useful_characters=minimum_useful_characters,
        pages=pages, nodes=nodes, unclassified=unclassified, warnings=warnings,
        summary=ExtractionSummary(
            page_count=len(pages), empty_page_count=sum(p.status == "OCR_CANDIDATE" for p in pages),
            total_characters=total, node_count=len(nodes), warning_count=len(warnings),
            status="NO_TEXT" if not useful else (
                "LOW_TEXT" if useful < minimum_useful_characters else "TEXT"
            ),
        ),
    )
    if len(result.canonical_bytes()) > max_output_bytes:
        raise ExtractionError(JobErrorCode.EXTRACTION_OUTPUT_LIMIT)
    return result
