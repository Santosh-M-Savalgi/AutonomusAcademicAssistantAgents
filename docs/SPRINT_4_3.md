# Phase 4.3: Structured output and TaskSpec registry

Phase 4.3 adds the deterministic structured-output foundation for future AAA
model tasks. It does not implement production lesson, question, grading,
retrieval, or agent pipelines.

## TaskSpec

`packages.model_client.taskspec.TaskSpec` is static task metadata. It contains:

- a lowercase stable task name and version;
- `text` or `structured` output mode;
- a small Pydantic output model for structured tasks;
- generation defaults (`model_id`, temperature, token limit, timeout);
- a strict validation policy with `max_retries` limited to 0 or 1;
- provider-neutral metadata.

The `TaskSpec` does not call a model, access a database, depend on FastAPI, or
contain task prompts/business workflows.

## Registry

`TaskSpecRegistry` is an in-memory deterministic registry. Exact task names are
registered directly. Task families use an explicit `family_prefix`, so
`lesson_block_*` is represented as a `lesson_block` TaskSpec with prefix
`lesson_block_`; the wildcard is a display/registration convention, not a
literal task identifier. Lookup resolves exact names first and then the most
specific matching family prefix. Duplicate registrations and invalid
definitions fail immediately.

The initial registry includes the specification task identifiers:

`syllabus_unit_extract`, `concept_extract`, `objective_extract`,
`prereq_propose`, `lesson_block_*`, `question_generate`, `question_tag`,
`answer_grade_rubric`, `misconception_classify`, `decision_explain`,
`diagnose_uncertain`, and `lesson_hard`.

The structured schemas are intentionally minimal placeholders. They are not
the future lesson/question/grading domain contracts.

## Structured-output pipeline

The gateway follows this sequence:

```text
TaskSpec
  -> deterministic Pydantic JSON Schema
  -> provider-neutral StructuredGenerationRequest
  -> raw/untrusted provider text
  -> JSON decoding
  -> strict Pydantic validation
  -> typed trusted result
```

`packages/model_client.schema.generate_json_schema` canonicalizes schema JSON
with sorted keys and preserves required fields, enums, and constraints. The
small provider subset rejects `$ref`/`$defs`, unions, and other constructs that
cannot be passed safely to the pinned structured-output path; it never silently
weakens a schema.

`StructuredGenerationResponse.data` is untrusted until its `validation.valid`
flag is true and the gateway has placed the validated Pydantic instance there.
Malformed JSON, missing fields, invalid enum values, invalid constraints, and
unexpected structures remain failures.

## Bounded retry behavior

The maximum is two total provider attempts: the initial attempt plus at most one
retry. Only deterministic structured-validation failures are retried. Provider
transport errors and timeouts are normalized and returned immediately. Exhausted
validation raises `StructuredOutputValidationError` with the task, attempt
count, and normalized validation messages. A zero-retry TaskSpec performs one
attempt only.

## Providers

`FakeProvider` supports deterministic raw structured sequences, including
malformed JSON followed by a valid candidate, schema-invalid candidates, and
repeated failures. All tests use this provider for gateway behavior.

`LlamaCppProvider` remains the only llama-server HTTP adapter. It receives the
generated schema through the OpenAI-compatible `response_format` field and
returns raw response text to the gateway. It does not perform final Pydantic
validation and does not start llama-server. Its provider-specific
`response_format` translation remains isolated from `packages/domain`.

Model/runtime/task provenance remains attached to successful structured results:
the existing model/provider/runtime/artifact metadata is preserved and the
resolved TaskSpec version is added. Retrieval, mastery, planner, and prompt
versions are not invented when they are unknown.

## Deferred

The following remain later-phase work: complete application-specific schemas and
semantic validators, schema compatibility evaluation against live llama.cpp,
production prompts and pipelines, TaskSpec routing/priority policy, retries with
jitter, circuit breaking, Redis caching, telemetry, cloud fallback, retrieval,
embeddings, and agent workflows.
