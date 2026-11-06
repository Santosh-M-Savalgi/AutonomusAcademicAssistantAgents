"""Gated host-native llama-server command construction and verification."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from packages.model_client.runtime import ModelRuntimeConfig, load_model_lock

_COMMON_FLAGS = (
    "--alias", "-m", "--host", "--port", "-c", "-np", "-ngl", "-b", "-ub", "--metrics"
)
_GPU_FLAGS = ("-fa", "-ctk", "-ctv")


def build_command(config: ModelRuntimeConfig, *, binary: str = "llama-server") -> list[str]:
    """Build the documented command; execution remains gated by help verification."""

    command = [
        binary,
        "--alias",
        "aaa-slm",
        "-m",
        str(config.artifact_path),
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "-c",
        str(config.context_tokens),
        "-np",
        str(config.parallel_slots),
        "-ngl",
        str(config.gpu_layers),
        "-b",
        str(config.batch_size),
        "-ub",
        str(config.ubatch_size),
    ]
    if config.profile == "gpu":
        command.extend(
            [
                "-fa",
                "on",
                "-ctk",
                config.cache_type_k,
                "-ctv",
                config.cache_type_v,
            ]
        )
    if config.metrics:
        command.append("--metrics")
    return command


def verify_help(binary: str, profile: str) -> str:
    """Run the pinned binary's help and ensure the command flags are available."""

    executable = shutil.which(binary)
    if executable is None:
        raise RuntimeError(
            f"{binary!r} is unavailable; install the pinned llama.cpp build "
            "before runtime verification"
        )
    result = subprocess.run(
        [executable, "--help"], check=False, capture_output=True, text=True, timeout=30
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        raise RuntimeError(f"{binary} --help failed with exit code {result.returncode}")
    required = list(_COMMON_FLAGS)
    if profile == "gpu":
        required.extend(_GPU_FLAGS)
    missing = [flag for flag in required if flag not in output]
    if missing:
        raise RuntimeError(f"{binary} --help is missing required flags: {', '.join(missing)}")
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("help", "print-command", "serve"))
    parser.add_argument(
        "--profile", choices=("cpu", "gpu"), default=os.getenv("AAA_PROFILE", "cpu")
    )
    parser.add_argument("--binary", default="llama-server")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--lock-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    defaults = ModelRuntimeConfig.for_profile(args.profile)
    config = ModelRuntimeConfig.for_profile(
        args.profile,
        artifact_path=args.model_path or defaults.artifact_path,
        lock_path=args.lock_path or defaults.lock_path,
    )
    if args.command == "help":
        print(verify_help(args.binary, args.profile))
        return 0
    command = build_command(config, binary=args.binary)
    if args.command == "print-command":
        print(" ".join(command))
        return 0
    verify_help(args.binary, args.profile)
    metadata = load_model_lock(config.lock_path)
    metadata.verify_file(config.artifact_path)
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
