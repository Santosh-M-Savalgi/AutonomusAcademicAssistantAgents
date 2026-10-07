"""Synthetic pypdf input, normalization, source/summary validation and hard limits."""

from io import BytesIO

import pytest

from packages.curriculum.pdf import ExtractionError, extract_pdf, normalize_text
from packages.domain.extraction import ExtractionResult
from tests.pdf_fixtures import document_source, syllabus_pdf


def extract(content, page_count, **overrides):
    limits = dict(max_bytes=20 * 1024 * 1024, max_pages=500, max_output_bytes=4 * 1024 * 1024,
                  minimum_useful_characters=40)
    limits.update(overrides)
    return extract_pdf(BytesIO(content), document_source(content, page_count), **limits)


def test_page_boundaries_unicode_empty_pages_and_table_text():
    content = syllabus_pdf([
        "Module I: Foundations\n1.1 Introduction\nCafé α β • concepts\nName    Hours\nTheory    3",
        "", "    ", "Module II: Applications\n2.1 Methods\n2.1.1 Practical Work",
    ])
    result = extract(content, 4)
    assert [page.number for page in result.pages] == [1, 2, 3, 4]
    assert "Café α β • concepts" in result.pages[0].text
    assert "Name  Hours\nTheory  3" in result.pages[0].text
    assert "Applications" not in result.pages[0].text
    assert result.pages[1].text == result.pages[2].text == ""
    assert result.summary.empty_page_count == 2
    assert [w.page for w in result.warnings if w.code == "NO_EXTRACTABLE_TEXT"] == [2, 3]
    assert result.summary.total_characters == sum(len(p.text) for p in result.pages)
    assert [n.source.page for n in result.nodes] == [1, 1, 4, 4, 4]
    assert ExtractionResult.model_validate_json(result.canonical_bytes()) == result
    assert result.canonical_bytes() == extract(content, 4).canonical_bytes()


def test_normalization_preserves_numbering_indentation_bullets_and_lines():
    assert normalize_text("  1.1 Heading\r\n\t• A\rB    C   \n\nEnd") == (
        "  1.1 Heading\n    • A\nB  C\n\nEnd"
    )
    assert normalize_text("word\nnext") == "word\nnext"


@pytest.mark.parametrize("pages", [[], [""], ["   ", ""]])
def test_empty_extraction_keeps_pages_and_flags_future_ocr(pages):
    result = extract(syllabus_pdf(pages), len(pages))
    assert result.summary.status == "NO_TEXT"
    assert result.summary.empty_page_count == len(pages)
    assert not result.nodes
    assert any(w.code == "LOW_TEXT" for w in result.warnings)


@pytest.mark.parametrize(("content", "count", "overrides", "code"), [
    (b"not a PDF", 1, {}, "INVALID_PDF"),
    (b"%PDF-1.7\nmalformed", 1, {}, "INVALID_PDF"),
    (syllabus_pdf(["private"], encrypted=True), 1, {}, "ENCRYPTED_PDF"),
    (syllabus_pdf(["large"]), 1, {"max_bytes": 10}, "PDF_LIMIT_EXCEEDED"),
    (syllabus_pdf(["one", "two"]), 2, {"max_pages": 1}, "PDF_LIMIT_EXCEEDED"),
    (syllabus_pdf(["one"]), 2, {}, "SOURCE_MISMATCH"),
    (syllabus_pdf(["text"]), 1, {"max_output_bytes": 10}, "EXTRACTION_OUTPUT_LIMIT"),
    (syllabus_pdf(["A" * 2000]), 1, {"max_output_bytes": 1024}, "EXTRACTION_OUTPUT_LIMIT"),
])
def test_invalid_or_excessive_pdfs_fail_explicitly(content, count, overrides, code):
    with pytest.raises(ExtractionError) as error:
        extract(content, count, **overrides)
    assert error.value.code == code


def test_embedded_actions_are_never_invoked(monkeypatch):
    # Extraction only reads page text; no attachments/action evaluator is called.
    from pypdf import PdfReader

    def forbidden(*args):
        pytest.fail("Attachment access is outside text extraction")

    monkeypatch.setattr(PdfReader, "attachments", property(forbidden))
    assert extract(syllabus_pdf(["Text only"]), 1).pages[0].text == "Text only"
