"""Deterministic tests for the Phase 4.1 local model runtime foundation."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.model_client.llama_server import build_command
from packages.model_client.runtime import (
    LLAMA_CPP_COMMIT,
    LLAMA_CPP_VERSION,
    MODEL_FILENAME,
    MODEL_ID,
    ModelArtifactMetadata,
    ModelRuntimeConfig,
    load_model_lock,
)


def test_profile_presets_keep_context_and_gpu_budget_bounded() -> None:
    cpu = ModelRuntimeConfig.for_profile("cpu")
    gpu = ModelRuntimeConfig.for_profile("gpu")

    assert cpu.context_tokens == 8192
    assert cpu.tokens_per_slot == 4096
    assert cpu.parallel_slots == 1
    assert cpu.gpu_layers == 0
    assert gpu.context_tokens == 8192
    assert gpu.tokens_per_slot == 4096
    assert gpu.parallel_slots == 2
    assert gpu.gpu_layers == 99
    assert gpu.flash_attention is True
    assert gpu.embeddings_cpu_only is True


def test_gpu_command_contains_the_locked_target_flags() -> None:
    command = build_command(ModelRuntimeConfig.for_profile("gpu"))

    assert command == [
        "llama-server",
        "--alias",
        "aaa-slm",
        "-m",
            "models/llama-3.2-3b-instruct-q4_k_m.gguf",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "-c",
        "8192",
        "-np",
        "2",
        "-ngl",
        "99",
        "-b",
        "512",
        "-ub",
        "512",
        "-fa",
        "on",
        "-ctk",
        "q8_0",
        "-ctv",
        "q8_0",
        "--metrics",
    ]


def test_invalid_runtime_budgets_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelRuntimeConfig(profile="gpu", parallel_slots=1, gpu_layers=99, flash_attention=True)

    with pytest.raises(ValidationError):
        ModelRuntimeConfig(profile="cpu", base_url="http://user:password@localhost:8080")

    with pytest.raises(ValidationError):
        ModelRuntimeConfig(profile="cpu", context_tokens=8193)

    with pytest.raises(ValidationError):
        ModelRuntimeConfig.for_profile("cpu", model_id="some-other-model")

    with pytest.raises(ValidationError):
        ModelRuntimeConfig.for_profile("cpu", artifact_path=Path("models/other.gguf"))


def test_model_lock_records_the_present_artifact() -> None:
    metadata = load_model_lock()

    assert metadata.model_id == MODEL_ID
    assert metadata.filename == MODEL_FILENAME
    assert metadata.llama_cpp_version == LLAMA_CPP_VERSION
    assert metadata.llama_cpp_commit == LLAMA_CPP_COMMIT
    assert metadata.artifact_present is True
    assert metadata.sha256 == "c55a83bfb6396799337853ca69918a0b9bbb2917621078c34570bc17d20fd7a1"
    assert metadata.source == "https://huggingface.co/hugging-quants/Llama-3.2-3B-Instruct-Q4_K_M-GGUF"


def test_present_artifact_requires_a_sha256_and_verifies_file(tmp_path: Path) -> None:
    artifact = tmp_path / MODEL_FILENAME
    artifact.write_bytes(b"deterministic test artifact")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata = ModelArtifactMetadata(
        model_id=MODEL_ID,
        filename=MODEL_FILENAME,
        format="GGUF",
        quantization="Q4_K_M",
        sha256=digest,
        source="test-fixture",
        license="test-license",
        llama_cpp_version=LLAMA_CPP_VERSION,
        llama_cpp_commit=LLAMA_CPP_COMMIT,
        artifact_present=True,
    )

    metadata.verify_file(artifact)

    with pytest.raises(ValidationError):
        ModelArtifactMetadata(**{**metadata.model_dump(), "sha256": ""})


def test_present_artifact_rejects_a_missing_file(tmp_path: Path) -> None:
    metadata = load_model_lock()

    with pytest.raises(FileNotFoundError, match="does not exist"):
        metadata.verify_file(tmp_path / MODEL_FILENAME)
