"""Agent 1: turn a text or PDF learning request into an ordered syllabus."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal, TypedDict, cast

from google import genai
from google.genai import types
from pypdf import PdfReader

from config import settings


class SyllabusTopic(TypedDict):
    topic_name: str
    subtopics: list[str]
    difficulty: Literal["beginner", "intermediate", "advanced"]
    prerequisite: str | None


SYLLABUS_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_name": {"type": "string"},
                    "subtopics": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["beginner", "intermediate", "advanced"],
                    },
                    "prerequisite": {"type": "STRING", "nullable": True},
                },
                "required": [
                    "topic_name",
                    "subtopics",
                    "difficulty",
                    "prerequisite",
                ],
            },
        }
    },
    "required": ["topics"],
}


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    """Create the Gemini client on first use, not during module import."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required to parse a syllabus")
    return genai.Client(api_key=settings.gemini_api_key)


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from every page of a syllabus PDF in page order."""
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_syllabus(
    raw_input: str = "", pdf_path: str | None = None
) -> list[SyllabusTopic]:
    """Generate a prerequisite-ordered curriculum from text and optional PDF text."""
    if pdf_path:
        pdf_text = extract_text_from_pdf(pdf_path)
        raw_input = (
            f"{raw_input}\n\nSyllabus document content:\n{pdf_text}".strip()
        )

    if not raw_input.strip():
        raise ValueError("raw_input or a PDF containing text is required")

    response = _get_client().models.generate_content(
        model=settings.syllabus_model,
        contents=(
            "Decompose this learning request into an ordered curriculum.\n"
            "Order topics so every prerequisite appears before what depends on it.\n"
            f'Student request: "{raw_input}"'
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SYLLABUS_SCHEMA,
            temperature=0.3,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty syllabus response")

    payload = json.loads(response.text)
    return cast(list[SyllabusTopic], payload["topics"])
