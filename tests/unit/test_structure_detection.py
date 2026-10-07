"""Pure hierarchy heuristics and rejection of invalid extraction contracts."""

from io import BytesIO
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.curriculum.pdf import extract_pdf
from packages.curriculum.structure import detect_structure
from packages.domain.extraction import ExtractedPage, ExtractionResult
from tests.pdf_fixtures import document_source, syllabus_pdf


def detect(text):
    return detect_structure(document_source(b"synthetic", 1),
                            [ExtractedPage(number=1, text=text, status="TEXT")])


def test_keyword_hierarchy_roman_and_decimal_numbering():
    nodes, _, _ = detect("Module I: Basics\nUnit 1: Algebra\nChapter I: Sets\n"
                         "Section 1.1 Relations\n1.1.1 Functions\n1.1.1.1 Composition\n"
                         "Module II: Advanced\n2.1 Analysis")
    assert [n.type for n in nodes] == ["MODULE", "UNIT", "CHAPTER", "SECTION", "TOPIC",
                                      "SUBTOPIC", "MODULE", "SECTION"]
    assert [n.parent_id for n in nodes[:6]] == [None] + [n.id for n in nodes[:5]]
    assert nodes[6].parent_id is None
    assert nodes[7].parent_id == nodes[6].id
    assert nodes[0].parse_confidence == 0.98
    assert nodes[4].parse_confidence == 0.9


def test_topics_nested_numbering_and_sibling_relationships():
    nodes, _, _ = detect("1. Introduction\n1.1 Background\n1.1.1 Detail\n1.2 History\n"
                         "2. Development")
    assert [n.type for n in nodes] == ["TOPIC", "SUBTOPIC", "SUBTOPIC", "SUBTOPIC", "TOPIC"]
    assert nodes[2].parent_id == nodes[1].id
    assert nodes[3].parent_id == nodes[0].id
    assert nodes[4].parent_id is None


def test_unclassified_paragraphs_ambiguous_numbering_and_false_positive_short_lines():
    text = ("Hello\nShort line\nModule Introduction\n1. this is a sentence.\n"
            "We discuss the module here.\nNote: optional\nIIV Invalid roman\n"
            "2026 Academic Year")
    nodes, refs, warnings = detect(text)
    assert nodes == []
    assert [(ref.line_start, ref.line_end) for ref in refs] == [(1, 8)]
    assert any(w.code == "AMBIGUOUS_HEADING" for w in warnings)


def test_repeated_caps_requires_context_and_common_syllabus_headings_are_conservative():
    text = "COURSE OVERVIEW\n\nA paragraph.\n\nLABORATORY WORK\n\nMore text.\nLearning Outcomes"
    nodes, _, _ = detect(text)
    assert [(n.detection_method, n.parse_confidence) for n in nodes] == [
        ("repeated_caps", 0.65), ("repeated_caps", 0.65), ("syllabus_heading", 0.85),
    ]
    assert detect("ONE CAPS TITLE\n\nparagraph")[0] == []


def test_repeated_identical_headings_have_unique_stable_source_ids():
    text = "Unit I: Basics\nbody\nUnit I: Basics\nbody"
    first = detect(text)
    assert first == detect(text)
    assert first[0][0].id != first[0][1].id
    assert [n.source.line_start for n in first[0]] == [1, 3]


@pytest.fixture
def valid_result():
    content = syllabus_pdf(["Module 1: Basics\n1.1 Introduction\nUnclassified body"])
    return extract_pdf(BytesIO(content), document_source(content, 1), max_bytes=100000,
                       max_pages=2, max_output_bytes=100000, minimum_useful_characters=1)


@pytest.mark.parametrize("corruption", ["duplicate", "parent", "page", "line", "order", "title",
                                       "cycle", "unclassified", "summary", "schema"])
def test_contract_rejects_invalid_hierarchy_and_traceability(valid_result, corruption):
    data = valid_result.model_dump()
    if corruption == "duplicate":
        data["nodes"].append(data["nodes"][0])
    elif corruption == "parent":
        data["nodes"][1]["parent_id"] = uuid4()
    elif corruption == "cycle":
        data["nodes"][0]["parent_id"] = data["nodes"][1]["id"]
    elif corruption in {"page", "line"}:
        data["nodes"][0]["source"]["page" if corruption == "page" else "line_end"] = 200
    elif corruption == "order":
        data["nodes"].reverse()
    elif corruption == "title":
        data["nodes"][0]["title"] = "Invented heading"
    elif corruption == "unclassified":
        data["unclassified"] = []
    elif corruption == "summary":
        data["summary"]["total_characters"] += 1
    elif corruption == "schema":
        data["schema_version"] = "future-schema"
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(data)
