"""Versioned deterministic prompt templates for Phase 4.6 evaluation."""

from __future__ import annotations

from packages.evalkit.contracts import (
    BenchmarkExample,
    GradingExample,
    GroundingExample,
    QuestionTagExample,
    SyllabusExample,
)

PROMPT_VERSION = "phase4.6-prompts-v6"
SUBJECT_NEUTRAL_PROMPT_VERSION = "phase4.6-prompts-v8"


def syllabus_prompt(example: BenchmarkExample) -> str:
    item = _as_syllabus(example)
    return (
        "Extract the core instructional concepts explicitly taught by the lesson material. "
        "Return only the structured output required by the task schema, using the items field. "
        "Return one short, canonical noun phrase per distinct concept. "
        "Use lowercase natural-language labels with spaces, "
        "with spaces between words rather than underscores or snake_case. "
        "Do not use identifier-style labels. "
        "Avoid activity descriptions and prefixes such as 'comparing', 'introducing', "
        "'identifying', 'using', or 'visualizing' when they only describe an activity. "
        "Do not return duplicate or overlapping labels for the same concept. "
        "Do not split one concept into multiple paraphrases or invent unsupported concepts. "
        "Preserve genuinely distinct concepts when the material covers more than one. "
        "Do not add explanations or unnecessary descriptive wording. "
        "Include only topics explicitly supported by the lesson material.\n\n"
        f"Lesson material:\n{item.input_material}"
    )


def question_tag_prompt(example: BenchmarkExample) -> str:
    item = _as_question_tag(example)
    return (
        "Assign the smallest sufficient set of 2 or 3 atomic instructional tags "
        "that describe the question. Prefer exactly 2 tags; add a third only when "
        "the question explicitly tests a distinct skill, operation, or representation "
        "that is not adequately captured by the first two tags. "
        "Do not require all vocabulary roles to be represented. "
        "Do not infer extra tags merely because a label is available in the vocabulary. "
        "Use canonical noun or concept forms, not verbs or -ing forms. "
        "Do not return duplicate tags. "
        "Make the first tag the core subject or topic of the question. "
        "Use any remaining tags only for distinct skills, operations, or representations "
        "explicitly tested by the question. "
        "Do not tag incidental words, numbers, units, or fragments from the question text. "
        "Use lowercase tags, and separate words in multi-word tags with spaces, not hyphens. "
        "Each tag must be one atomic topic or skill, not a descriptive phrase or sentence. "
        "Do not use generic subject tags such as 'math'. "
        "Return only the structured output required by the task schema, using the tags field. "
        "Do not add explanations or tags unsupported by the question.\n\n"
        f"Question:\n{item.input_material}"
    )


def subject_neutral_question_tag_prompt(example: BenchmarkExample) -> str:
    item = _as_question_tag(example)
    return (
        "Assign the smallest sufficient set of 2 or 3 atomic instructional tags "
        "that describe the question. Prefer exactly 2 tags; add a third only when "
        "the question explicitly tests a distinct skill, operation, or representation "
        "that is not adequately captured by the first two tags. "
        "Do not require all vocabulary roles to be represented. "
        "Do not infer extra tags merely because a label is available in the vocabulary. "
        "Use canonical noun or concept forms, not verbs or -ing forms. "
        "Do not return duplicate tags. "
        "Make the first tag the core subject or topic of the question. "
        "Use any remaining tags only for distinct skills, operations, or representations "
        "explicitly tested by the question. "
        "When the question explicitly asks you to compare, contrast, rank, or determine "
        "which option is greater or less, include the comparison tag when comparison is "
        "genuinely part of the task; do not apply it to incidental comparative wording. "
        "Do not tag incidental words, numbers, units, or fragments from the question text. "
        "Use lowercase tags, and separate words in multi-word tags with spaces, not hyphens. "
        "Each tag must be one atomic topic or skill, not a descriptive phrase or sentence. "
        "Do not use generic subject labels such as 'math', 'science', or a broad school subject. "
        "Return only the structured output required by the task schema, using the tags field. "
        "Do not add explanations or tags unsupported by the question.\n\n"
        f"Question:\n{item.input_material}"
    )


def grading_prompt(example: BenchmarkExample) -> str:
    item = _as_grading(example)
    return (
        "Grade the supplied response against the described rubric context. "
        "Return only the structured output required by the task schema. "
        "Include the confidence value required by the schema.\n\n"
        f"Grading material:\n{item.input_material}"
    )


def grounding_prompt(example: BenchmarkExample) -> str:
    item = _as_grounding(example)
    if not item.source_context:
        raise ValueError("grounding examples require visible source context")
    source_context = "\n".join(
        f"- [{source.source_id}] {source.content}" for source in item.source_context
    )
    return (
        "Identify the source identifiers that support the answer. "
        "Return only the structured output required by the evaluation task schema. "
        "Do not invent source identifiers and do not add explanations.\n\n"
        f"Grounding material:\n{item.input_material}\n\n"
        f"Available source context:\n{source_context}"
    )


def _as_syllabus(example: BenchmarkExample) -> SyllabusExample:
    if not isinstance(example, SyllabusExample):
        raise TypeError("expected a SyllabusExample")
    return example


def _as_question_tag(example: BenchmarkExample) -> QuestionTagExample:
    if not isinstance(example, QuestionTagExample):
        raise TypeError("expected a QuestionTagExample")
    return example


def _as_grading(example: BenchmarkExample) -> GradingExample:
    if not isinstance(example, GradingExample):
        raise TypeError("expected a GradingExample")
    return example


def _as_grounding(example: BenchmarkExample) -> GroundingExample:
    if not isinstance(example, GroundingExample):
        raise TypeError("expected a GroundingExample")
    return example
