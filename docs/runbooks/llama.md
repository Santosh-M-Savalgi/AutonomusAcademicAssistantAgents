# Local llama.cpp runtime

This runbook covers the Phase 4.1 model-runtime foundation. It starts a
host-native `llama-server`; it does not add a model provider or Model Gateway.
The API and worker continue to use the deterministic `mock` profile by default.

## Pinned inputs

| Input | Pin or value |
|---|---|
| Model | `meta-llama/Llama-3.2-3B-Instruct` |
| Artifact | `models/llama-3.2-3b-instruct-q4_k_m.gguf` |
| Format/quantization | GGUF / Q4_K_M |
| llama.cpp release | `v0.6.0` |
| llama.cpp commit | `8345f333951c661d166b00e6f9362e553768f292` |
| CUDA Toolkit | `13.3` (`nvcc 13.3.73`) |
| GPU | NVIDIA RTX 3050 Laptop GPU, 4 GB VRAM |
| Server address | `127.0.0.1:8080` |
| Context / slots | `8192` / `2` |
| Effective context per slot | `4096` (verified through `/v1/models`) |

The release is recorded for reproducibility. It is not a Python dependency and
is not installed by the application image. The release is licensed under MIT;
the model is subject to the Llama 3.2 Community License. The exact artifact
SHA-256 is recorded in `models/MODELS.lock`:

```text
c55a83bfb6396799337853ca69918a0b9bbb2917621078c34570bc17d20fd7a1
```

## Human prerequisite: source and license acceptance

The model license was accepted before obtaining the artifact from the trusted
source recorded in `models/MODELS.lock`. Place the verified file at:

```text
models/llama-3.2-3b-instruct-q4_k_m.gguf
```

The `llama-up` target verifies the lock and file checksum before starting.

## Build llama.cpp in WSL

Use a WSL/Linux checkout outside this application repository or a dedicated
tool directory. The source and build are not part of the AAA application image.

```bash
git clone https://github.com/ggml-org/llama.cpp.git ~/src/llama.cpp
cd ~/src/llama.cpp
git checkout 8345f333951c661d166b00e6f9362e553768f292
cmake -S . -B build-cuda -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build-cuda --config Release --target llama-server -j
export PATH="$HOME/src/llama.cpp/build-cuda/bin:$PATH"
```

For CPU-only use, build a separate binary with `-DGGML_CUDA=OFF` and use the
same model artifact and application configuration:

```bash
cmake -S . -B build-cpu -DGGML_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-cpu --config Release --target llama-server -j
export PATH="$HOME/src/llama.cpp/build-cpu/bin:$PATH"
```

Verify the selected binary and GPU:

```bash
git -C ~/src/llama.cpp rev-parse HEAD
nvidia-smi
llama-server --help
```

The command syntax was verified against the pinned llama.cpp `v0.6.0`
`llama-server --help`. In particular, this build exposes the KV-cache flags as
`-ctk, --cache-type-k` and `-ctv, --cache-type-v`; the short spellings are used
below and by the command builder.

## GPU profile

After the human prerequisite is complete, run:

```bash
make llama-help AAA_PROFILE=gpu
make llama-up AAA_PROFILE=gpu
```

The wrapper verifies `llama-server --help`, validates the lock and artifact,
then executes this verified command:

```text
llama-server -m models/llama-3.2-3b-instruct-q4_k_m.gguf --alias aaa-slm \
  --host 127.0.0.1 --port 8080 -c 8192 -np 2 -ngl 99 -b 512 -ub 512 \
  -fa on -ctk q8_0 -ctv q8_0 --metrics
```

This command was run successfully on the verified RTX 3050/CUDA environment.

## CPU profile

Use the same artifact and endpoint configuration with GPU offload disabled:

```bash
make llama-help AAA_PROFILE=cpu
make llama-up AAA_PROFILE=cpu
```

The CPU command uses `-ngl 0`, one slot, the same `-c 8192` context, and the
same `--metrics` endpoint. Embedding inference remains CPU-only for this
hardware profile; embedding selection and retrieval are later-phase work.

## Compose profiles and application configuration

The existing Compose `mock`, `cpu`, and `gpu` profiles remain intact. The API
and worker receive `MODEL_BASE_URL`, model identity, artifact path, lock path,
and llama.cpp release through environment variables. Compose maps
`host.docker.internal` to the host so the application containers can reach the
host-native server. The `mock` profile does not make a model request.

For Compose-based API development, copy `.env.example` and set:

```dotenv
AAA_PROFILE=cpu
MODEL_BASE_URL=http://host.docker.internal:8080
```

If the API is run directly on the host instead of through Compose, use
`MODEL_BASE_URL=http://127.0.0.1:8080`.

## Health and metrics

The verified server was checked with:

```bash
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/v1/models
curl --fail http://127.0.0.1:8080/metrics
```

`/health` returned successfully while the model was loaded. `/v1/models`
reported alias `aaa-slm` and an effective context of 4096 tokens per slot.
An OpenAI-compatible `/v1/chat/completions` request also completed
successfully. The smoke request was a real local inference check, not a unit
test or a formal benchmark.

The application runtime does not treat these endpoints as proof that a model
artifact is trusted; lock and checksum validation remains local to `llama-up`.

## RTX 3050 4 GB OOM ladder

The target hardware is an RTX 3050 with 4 GB VRAM, 16 GB system RAM, and an
i5-12500H. The loaded server used approximately 2571 MiB of the 4096 MiB
available VRAM. If the target GPU profile reports an out-of-memory error, apply the
following changes in order and re-run the gated help check each time:

1. Change `-ub 512` to `-ub 256`.
2. Change `-np 2 -c 8192` to `-np 1 -c 6144`.
3. Change `-ngl 99` to `-ngl 24`.

Do not increase context beyond 8192. With two slots, the intended per-slot
budget is 4096 tokens.

The measured local smoke test produced approximately 44.14 tokens/second of
generation and 51.27 tokens/second of prompt processing. These are observed
single-run smoke-test measurements for this machine and configuration, not a
formal benchmark or capacity claim.

Embedding inference remains CPU-only on this machine. Do not place the future
embedding server or CPU embedding fallback on the 4 GB chat GPU. Ollama is not
part of the AAA runtime architecture; the selected runtime is host-native
llama.cpp `llama-server` behind the future Model Gateway.

## Stop and troubleshooting

Stop a foreground server with `Ctrl-C`. The application services can be
started independently after the host server is ready:

```bash
AAA_PROFILE=gpu make up
```

Useful checks:

```bash
test -f models/llama-3.2-3b-instruct-q4_k_m.gguf
uv run --locked python -m packages.model_client.llama_server print-command --profile gpu
make llama-help AAA_PROFILE=gpu
```

If the binary is missing, the model lock is pending, the artifact is absent,
or its digest is wrong, stop and resolve that human prerequisite rather than
starting with an unverified model.
