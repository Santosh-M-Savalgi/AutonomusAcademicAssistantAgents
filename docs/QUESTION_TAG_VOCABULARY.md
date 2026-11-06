# Phase 4.6 Question-Tag Vocabulary

## Manifest

- Vocabulary ID: `question-tags`
- Version: `1.0.0`
- Scope: Phase 4.6 synthetic benchmark seed
- Status: partial and non-exhaustive
- Live model output: canonical labels only

This vocabulary is the initial controlled slice required by the two synthetic
question-tag fixtures. It is not the complete educational tagging taxonomy.
Labels must not be added automatically when a model produces an unknown term.

| Canonical label | Role | Compatibility-only aliases |
|---|---|---|
| `fractions` | topic | `fraction` |
| `comparison` | skill | `compare`, `comparing` |
| `number line` | representation | `number-line`, `numberline` |

Aliases are retained for compatibility and migration purposes only. They are
not accepted by the live `question-tag-v2` structured output schema. Unknown
labels and duplicate labels invalidate the complete response; they are not
dropped, fuzzy-matched, or mapped to the nearest canonical label.

## Versioning

The task contract is `question-tag-v2` and references this vocabulary version.
Alias-only additions may use a compatible vocabulary revision. Adding,
removing, renaming, or changing the meaning of a canonical label requires a
new vocabulary/task revision and a separately identified evaluation run.
Historical reports remain associated with their original vocabulary version.

## Validation-success gate

The benchmark reports `question_tag_validation_success_rate` as a separate
gate metric. No validation-success threshold is specified by the project
requirements, so the gate is currently marked pending owner approval rather
than assigned an invented numeric threshold. The existing question-tag
precision threshold remains `0.85`.
