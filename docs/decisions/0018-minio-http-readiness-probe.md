# ADR 0018: Dedicated HTTP probe for shell-less MinIO image

## Status

Accepted for Sprint 1.3.

## Decision

Use a dedicated, digest-pinned `curlimages/curl` Compose sidecar to check
`http://minio:9000/minio/health/live`. The sidecar remains running with a
minimal sleep process and exposes its own Compose health status. The API and
the integration fixture depend on the sidecar becoming healthy. The MinIO
service has no in-container healthcheck; Compose only requires it to be running
before starting the probe.

The pinned probe image is:

```text
curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6
```

The MinIO image itself remains unchanged and is not expected to contain a
shell, curl, wget, Python, or any other probe utility. The application-level
`/readyz` endpoint continues to perform its authenticated MinIO SDK check.

## Rationale and trade-offs

- A process-existence check would not prove that MinIO accepts HTTP requests.
- A host-side probe would not participate in Docker Compose's health graph and
  would make `docker compose --wait` behavior differ between development and CI.
- The sidecar adds one small infrastructure image and container, but keeps the
  actual HTTP readiness condition portable and identical in development and
  integration environments.
- The probe has no published ports and uses the internal Compose network only.
- Existing MinIO credentials, storage, command, ports, and API readiness logic
  remain unchanged.
