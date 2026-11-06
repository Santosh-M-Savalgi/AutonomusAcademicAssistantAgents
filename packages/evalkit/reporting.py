"""Generated JSON and Markdown reports for Phase 4.6."""

from __future__ import annotations

from pathlib import Path

from packages.evalkit.canonical import canonical_report_json
from packages.evalkit.contracts import EvaluationSuiteReport, GateEvaluation


def write_reports(report: EvaluationSuiteReport, output_dir: Path) -> tuple[Path, Path]:
    report_dir = output_dir / "phase4.6" / report.run_id
    report_dir = _collision_safe_directory(report_dir, report)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "SPRINT_4_6_EVALUATION.json"
    markdown_path = report_dir / "SPRINT_4_6_EVALUATION.md"
    json_path.write_text(canonical_report_json(report) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _collision_safe_directory(
    report_dir: Path, report: EvaluationSuiteReport
) -> Path:
    """Keep a run ID stable while refusing to overwrite a different report."""

    if not report_dir.exists():
        return report_dir
    expected_json = canonical_report_json(report) + "\n"
    json_path = report_dir / "SPRINT_4_6_EVALUATION.json"
    markdown_path = report_dir / "SPRINT_4_6_EVALUATION.md"
    if (
        json_path.exists()
        and markdown_path.exists()
        and json_path.read_text(encoding="utf-8") == expected_json
        and markdown_path.read_text(encoding="utf-8") == render_markdown(report)
    ):
        return report_dir
    suffix = 1
    while True:
        candidate = report_dir.parent / f"{report_dir.name}-{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def render_markdown(report: EvaluationSuiteReport) -> str:
    lines = [
        "# Sprint 4.6 — 3B Local Model Evaluation",
        "",
        f"**Decision:** {report.decision}",
        f"**Status:** {report.status}",
        f"**Run ID:** `{report.run_id}`",
        f"**Timestamp:** `{report.timestamp.isoformat()}`",
        f"**Decision reason:** {report.decision_reason or 'none recorded'}",
        "",
        "## Runtime",
        "",
        f"- Provider: `{report.runtime.provider}`",
        f"- Endpoint: `{report.runtime.endpoint}`",
        f"- Model: `{report.runtime.model_id}`",
        f"- Artifact SHA-256: `{report.runtime.artifact_sha256}`",
        f"- Preflight: **{report.runtime.status}**",
        f"- Returned model IDs: `{', '.join(report.runtime.returned_model_ids) or 'none'}`",
        f"- Error: {report.runtime.error or 'none'}",
        "",
        "## Dataset inventory",
        "",
        "| Benchmark | Dataset | Version | Samples | Metrics |",
        "|---|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {entry.benchmark_name} | `{entry.dataset.dataset_id}` | "
        f"`{entry.dataset.version}` | {entry.sample_count} | "
        f"{', '.join(entry.metric_names)} |"
        for entry in report.datasets
    )
    lines.extend(
        [
            "",
            "## Prompt versions",
            "",
            f"- Suite field: `{report.prompt_version}`",
            *[
                f"- `{benchmark_key}`: `{prompt_version}`"
                for benchmark_key, prompt_version in sorted(report.prompt_versions.items())
            ],
        ]
    )
    lines.extend(
        [
            "",
            "## Mandatory gates",
            "",
            "| Gate | Blocking | Metric | Result | Threshold | Status | Samples | Dataset |",
            "|---|:---:|---|---:|---:|---|---:|---|",
        ]
    )
    for gate in _gates(report):
        lines.append(
            f"| {gate.name} | {'yes' if gate.blocking else 'no'} | {gate.metric_name} | "
            f"{_value(gate.value)} | "
            f"{_value(gate.threshold)} | {_gate_status(gate)} | {gate.sample_count} | "
            f"`{gate.dataset.dataset_id}:{gate.dataset.version}` |"
        )
    lines.extend(["", "## Benchmark details", ""])
    for benchmark in report.benchmarks:
        model_id = benchmark.metadata.model.model_id if benchmark.metadata.model else "unavailable"
        benchmark_lines = [
            f"### {benchmark.metadata.benchmark_name}",
            "",
            f"- Benchmark key: `{benchmark.metadata.benchmark_key or 'unspecified'}`",
            f"- Scope: `{benchmark.metadata.scope or 'unspecified'}`",
            f"- Dataset: `{benchmark.metadata.dataset.dataset_id}:"
            f"{benchmark.metadata.dataset.version}`",
            f"- Task: `{benchmark.metadata.task}` "
            f"({benchmark.metadata.task_version})",
            f"- Prompt version: `{benchmark.metadata.prompt_version}`",
            f"- Provider: `{benchmark.metadata.provider or 'unavailable'}`",
            f"- Runtime: `{benchmark.metadata.runtime_id or 'unavailable'}`",
            f"- Model: `{model_id}`",
            f"- Artifact: `{benchmark.metadata.artifact_version or 'unavailable'}`",
            f"- Schema: `{benchmark.metadata.schema_id or 'unavailable'}`",
            f"- Schema SHA-256: `{benchmark.metadata.schema_hash or 'unavailable'}`",
            f"- Samples: {benchmark.metadata.sample_count}",
            f"- Successful: {benchmark.metadata.successful_count}",
            f"- Failed: {benchmark.metadata.failed_count}",
            f"- Latency p50/p95/p99 ms: {_value(benchmark.latency.p50_ms)} / "
            f"{_value(benchmark.latency.p95_ms)} / {_value(benchmark.latency.p99_ms)}",
            f"- Tokens prompt/completion/total: "
            f"{benchmark.throughput.prompt_tokens} / "
            f"{benchmark.throughput.completion_tokens} / "
            f"{benchmark.throughput.total_tokens}",
        ]
        benchmark_lines.extend(
            [
                "- Metrics:",
                *[
                    f"  - `{metric_name}`: {_value(metric_value)}"
                    for metric_name, metric_value in sorted(benchmark.metrics.items())
                ],
            ]
        )
        if benchmark.metadata.vocabulary_id is not None:
            benchmark_lines.insert(
                4,
                f"- Vocabulary: `{benchmark.metadata.vocabulary_id}@"
                f"{benchmark.metadata.vocabulary_version}`",
            )
        lines.extend(benchmark_lines)
        if benchmark.structured_output is not None:
            lines.append(f"- Structured output: `{benchmark.structured_output.model_dump()}`")
        if benchmark.errors:
            lines.append(f"- Errors: `{benchmark.errors}`")
        lines.append("")
    lines.extend(
        [
            "## Throughput",
            "",
            f"- Prompt processing tok/s: {_value(report.server_prompt_tokens_per_second)}",
            f"- Generation tok/s: {_value(report.server_generation_tokens_per_second)}",
            "",
            "## Embedding evaluation",
            "",
            f"- BGE-small: **{report.embedding.status}** — "
            f"{report.embedding.reason or 'completed'}",
            "- Nomic challenger: **"
            f"{report.challenger.status if report.challenger else 'NOT_RUN'}**",
            "",
            "## Limitation",
            "",
            report.dataset_limitation,
            "",
        ]
    )
    if report.errors:
        lines.extend(["## Errors", "", *[f"- {error}" for error in report.errors], ""])
    return "\n".join(lines)


def _gates(report: EvaluationSuiteReport) -> list[GateEvaluation]:
    return [gate for benchmark in report.benchmarks for gate in benchmark.gates]


def _value(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.6f}"


def _gate_status(gate: GateEvaluation) -> str:
    if gate.status is not None:
        return gate.status
    if gate.threshold is None:
        return "BLOCKED_PENDING_DECISION"
    if not gate.available:
        return "BLOCKED_PENDING_EVALUATION"
    return "PASS" if gate.passed else "FAIL"
