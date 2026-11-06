# Subject-Neutral Question-Tag Vocabulary

## Manifest

- Vocabulary ID: `question-tags`
- Version: `2.0.0`
- Scope: Phase 4.6 subject-neutral synthetic benchmark seed
- Status: partial and non-exhaustive
- Task: `question_tag_v3` / `question-tag-v3`
- Live model output: canonical labels only

This vocabulary is a separately versioned expansion. The original
`question-tags@1.0.0` vocabulary and `question-tag-v2` task remain unchanged.

## Canonical labels

| Canonical label | Role | Subject or scope |
|---|---|---|
| `fractions` | topic | mathematics |
| `equations` | topic | mathematics |
| `algorithms` | topic | computer science |
| `data structures` | topic | computer science |
| `forces` | topic | physics |
| `waves` | topic | physics |
| `matter` | topic | chemistry |
| `chemical reactions` | topic | chemistry |
| `cells` | topic | biology |
| `genetics` | topic | biology |
| `comparison` | skill | cross-cutting |
| `calculation` | skill | cross-cutting |
| `number line` | representation | cross-cutting |
| `diagram` | representation | cross-cutting |

The existing v1 compatibility aliases are retained only for the unchanged
labels `fractions`, `comparison`, and `number line`. They are not accepted as
live output. New labels have no aliases.

## Annotation guidance

1. Assign the smallest sufficient set of two or three tags.
2. Prefer exactly two tags. Add a third only when the question explicitly tests
   a distinct skill, operation, or representation that the first two tags do
   not adequately capture.
3. Use a **topic** tag for the primary subject matter being assessed, such as
   `forces`, `cells`, or `algorithms`.
4. Use a **skill** tag only when the question explicitly asks the learner to
   perform that operation, such as `comparison` or `calculation`.
5. Use a **representation** tag only when the question explicitly uses or
   interprets that representation, such as a `number line` or `diagram`.
6. Do not require every role to appear. A question may have two topics, a topic
   and a skill, or a topic and a representation when that is the smallest
   sufficient description.
7. For questions spanning multiple categories, include each distinct topic or
   operation that is explicitly assessed, then stop at the smallest sufficient
   set. Do not tag incidental words, units, examples, or available vocabulary
   labels that are not required to answer the question.
8. Use canonical lowercase labels exactly as written. Do not add synonyms,
   aliases, fuzzy matches, or duplicate labels.

## Schema and versioning

The v3 generation schema uses finite `anyOf` branches with `const` and
remaining-label `enum` constraints. It permits every distinct ordered sequence
of two or three canonical labels without relying on `uniqueItems`, which is not
enforced by the pinned llama.cpp runtime. The schema contains 196 branches for
14 labels and expands to 182 ordered pairs plus 2,184 ordered triples.

Adding canonical labels changes the task's meaning, so this vocabulary uses a
new task revision. Historical reports remain associated with
`question-tags@1.0.0` and `question-tag-v2`.
