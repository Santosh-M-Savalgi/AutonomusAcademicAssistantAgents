"""Validated configuration and artifact bookkeeping for the local model runtime.

This module deliberately stops at the llama.cpp process boundary.  It does not
make model requests, define a gateway, or provide a curriculum provider.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RuntimeProfile = Literal["mock", "cpu", "gpu"]

MODEL_ID: Final = "meta-llama/Llama-3.2-3B-Instruct"
MODEL_FILENAME: Final = "llama-3.2-3b-instruct-q4_k_m.gguf"
MODEL_FORMAT: Final = "GGUF"
MODEL_QUANTIZATION: Final = "Q4_K_M"
LLAMA_CPP_VERSION: Final = "v0.6.0"
LLAMA_CPP_COMMIT: Final = "8345f333951c661d166b00e6f9362e553768f292"
DEFAULT_MODEL_BASE_URL: Final = "http://127.0.0.1:8080"
DEFAULT_MODEL_PATH: Final = Path("models") / MODEL_FILENAME
DEFAULT_MODEL_LOCK_PATH: Final = Path("models") / "MODELS.lock"
MAX_CONTEXT_TOKENS: Final = 8192
TOKENS_PER_SLOT: Final = 4096
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ModelArtifactMetadata(BaseModel):
    """The minimum provenance and verification record for one GGUF artifact."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    format: Literal["GGUF"]
    quantization: Literal["Q4_K_M"]
    sha256: str = ""
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)
    llama_cpp_version: str = Field(min_length=1)
    llama_cpp_commit: str = Field(min_length=7)
    artifact_present: bool = False

    @field_validator("sha256", mode="before")
    @classmethod
    def normalize_sha256(cls, value: object) -> str:
        """Accept a blank pending digest, otherwise require lowercase hex."""

        if not isinstance(value, str):
            raise ValueError("sha256 must be a hexadecimal string or blank while pending")
        digest = value.strip().lower()
        if digest and _SHA256_RE.fullmatch(digest) is None:
            raise ValueError("sha256 must contain exactly 64 lowercase hexadecimal characters")
        return digest

    @model_validator(mode="after")
    def require_digest_for_present_artifact(self) -> ModelArtifactMetadata:
        if self.artifact_present and not self.sha256:
            raise ValueError("an available model artifact must have a sha256 digest")
        if self.filename != MODEL_FILENAME:
            raise ValueError(f"model filename must be {MODEL_FILENAME}")
        if self.model_id != MODEL_ID:
            raise ValueError(f"model_id must be {MODEL_ID}")
        if self.llama_cpp_version != LLAMA_CPP_VERSION:
            raise ValueError(f"llama_cpp_version must be pinned to {LLAMA_CPP_VERSION}")
        if self.llama_cpp_commit != LLAMA_CPP_COMMIT:
            raise ValueError("llama_cpp_commit does not match the pinned llama.cpp release")
        return self

    def verify_file(self, path: Path) -> None:
        """Verify that ``path`` exists and matches the recorded digest."""

        if not self.artifact_present or not self.sha256:
            raise RuntimeError("model artifact metadata is pending a trusted human-provided file")
        if not path.is_file():
            raise FileNotFoundError(f"model artifact does not exist: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != self.sha256:
            raise RuntimeError(f"sha256 mismatch for model artifact: {path}")


def load_model_lock(path: Path = DEFAULT_MODEL_LOCK_PATH) -> ModelArtifactMetadata:
    """Load and validate the TOML model lock without downloading anything."""

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"model lock does not exist: {path}") from exc
    artifact = document.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError("model lock must contain an [artifact] table")
    return ModelArtifactMetadata.model_validate(artifact)


class ModelRuntimeConfig(BaseModel):
    """Resource and endpoint settings shared by CPU and GPU model profiles."""

    model_config = ConfigDict(extra="forbid")

    profile: RuntimeProfile
    base_url: str = DEFAULT_MODEL_BASE_URL
    model_id: str = MODEL_ID
    artifact_path: Path = DEFAULT_MODEL_PATH
    lock_path: Path = DEFAULT_MODEL_LOCK_PATH
    context_tokens: int = Field(default=MAX_CONTEXT_TOKENS, ge=1, le=MAX_CONTEXT_TOKENS)
    parallel_slots: int = Field(default=1, ge=1, le=2)
    tokens_per_slot: int = Field(default=TOKENS_PER_SLOT, ge=1, le=TOKENS_PER_SLOT)
    gpu_layers: int = Field(default=0, ge=0)
    batch_size: int = Field(default=512, ge=1, le=512)
    ubatch_size: int = Field(default=512, ge=1, le=512)
    flash_attention: bool = False
    cache_type_k: Literal["q8_0"] = "q8_0"
    cache_type_v: Literal["q8_0"] = "q8_0"
    metrics: bool = True
    embeddings_cpu_only: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("base_url must not contain credentials")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_context_budget(self) -> ModelRuntimeConfig:
        if self.model_id != MODEL_ID:
            raise ValueError(f"model_id must be pinned to {MODEL_ID}")
        if self.artifact_path.name != MODEL_FILENAME:
            raise ValueError(f"artifact filename must be {MODEL_FILENAME}")
        if self.context_tokens // self.parallel_slots < self.tokens_per_slot:
            raise ValueError("context_tokens must provide the required tokens_per_slot per slot")
        if self.profile == "gpu" and self.parallel_slots != 2:
            raise ValueError("gpu profile requires exactly two parallel slots")
        if self.profile != "gpu" and self.gpu_layers != 0:
            raise ValueError("mock and cpu profiles must keep gpu_layers at zero")
        if self.profile == "gpu" and not self.flash_attention:
            raise ValueError("gpu profile requires flash attention")
        return self

    @classmethod
    def for_profile(
        cls,
        profile: RuntimeProfile,
        *,
        base_url: str = DEFAULT_MODEL_BASE_URL,
        model_id: str = MODEL_ID,
        artifact_path: Path = DEFAULT_MODEL_PATH,
        lock_path: Path = DEFAULT_MODEL_LOCK_PATH,
    ) -> ModelRuntimeConfig:
        """Build the only supported Phase 4.1 resource presets."""

        if profile == "gpu":
            return cls(
                profile=profile,
                base_url=base_url,
                model_id=model_id,
                artifact_path=artifact_path,
                lock_path=lock_path,
                parallel_slots=2,
                gpu_layers=99,
                flash_attention=True,
            )
        return cls(
            profile=profile,
            base_url=base_url,
            model_id=model_id,
            artifact_path=artifact_path,
            lock_path=lock_path,
        )
