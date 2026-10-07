"""Disposable bounded process for MinIO I/O and pypdf. Only safe status on stdout."""

import ctypes
import logging
import math
import os
import resource
import signal
import sys
import tempfile
import warnings

from minio.error import S3Error
from pydantic import Field
from urllib3.exceptions import HTTPError

from apps.worker.extraction_config import ExtractionSettings
from packages.curriculum.pdf import ExtractionError, extract_pdf
from packages.domain.extraction import DocumentSource
from packages.domain.jobs import JobErrorCode
from packages.domain.models import DomainModel
from packages.persistence.extractions import SourceResolutionError, persist_extraction
from packages.persistence.object_storage import (
    ObjectIntegrityError,
    ObjectLimitError,
    ObjectStorage,
    ObjectStorageSettings,
)


class ExtractionRequest(DomainModel):
    source: DocumentSource
    object_key: str
    storage: ObjectStorageSettings = Field(repr=False)
    limits: ExtractionSettings
    max_pdf_bytes: int = Field(gt=0, le=20 * 1024 * 1024)
    max_pdf_pages: int = Field(ge=1, le=10000)
    parent_pid: int = Field(gt=0)


class ExtractionOutcome(DomainModel):
    result_ref: str | None = Field(default=None, max_length=512)
    error_code: JobErrorCode | None = None
    retryable: bool = False


def process_request(request: ExtractionRequest) -> ExtractionOutcome:
    storage = ObjectStorage(request.storage)
    try:
        # Anonymous/unlinked file: the kernel also closes it on SIGKILL/parent death.
        with tempfile.TemporaryFile(mode="w+b", dir=".") as pdf:
            storage.download_into(
                request.object_key, pdf, max_bytes=request.max_pdf_bytes,
                expected_size=request.source.size_bytes, expected_sha256=request.source.sha256,
            )
            result = extract_pdf(
                pdf, request.source, max_bytes=request.max_pdf_bytes,
                max_pages=request.max_pdf_pages, max_output_bytes=request.limits.max_output_bytes,
                minimum_useful_characters=request.limits.minimum_useful_characters,
            )
        try:
            reference = persist_extraction(storage, result, request.limits.max_output_bytes)
        except (ObjectIntegrityError, ObjectLimitError):
            return ExtractionOutcome(error_code=JobErrorCode.ARTIFACT_CONFLICT)
        except S3Error:
            return ExtractionOutcome(error_code=JobErrorCode.STORAGE_UNAVAILABLE, retryable=True)
        return ExtractionOutcome(result_ref=reference)
    except (ExtractionError, SourceResolutionError) as error:
        return ExtractionOutcome(error_code=error.code)
    except ObjectLimitError:
        return ExtractionOutcome(error_code=JobErrorCode.PDF_LIMIT_EXCEEDED)
    except ObjectIntegrityError:
        return ExtractionOutcome(error_code=JobErrorCode.SOURCE_MISMATCH)
    except S3Error as error:
        if error.code in {"NoSuchKey", "NoSuchBucket"}:
            return ExtractionOutcome(error_code=JobErrorCode.SOURCE_NOT_FOUND)
        return ExtractionOutcome(error_code=JobErrorCode.STORAGE_UNAVAILABLE, retryable=True)
    except HTTPError:
        return ExtractionOutcome(error_code=JobErrorCode.STORAGE_UNAVAILABLE, retryable=True)
    except MemoryError:
        return ExtractionOutcome(error_code=JobErrorCode.EXTRACTION_RESOURCE_LIMIT)
    finally:
        storage.close_sync()


def main() -> None:
    # pypdf/SDK diagnostics may contain untrusted strings; never forward them to worker logs.
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        request = ExtractionRequest.model_validate_json(sys.stdin.buffer.read(64 * 1024 + 1))
        libc = ctypes.CDLL(None)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != request.parent_pid:
            raise RuntimeError("Parent unavailable")
        memory = request.limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        cpu = max(1, math.ceil(request.limits.timeout_seconds))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE, (request.max_pdf_bytes, request.max_pdf_bytes))
        outcome = process_request(request)
    except Exception:
        outcome = ExtractionOutcome(error_code=JobErrorCode.HANDLER_EXCEPTION, retryable=True)
    sys.stdout.write(outcome.model_dump_json())


if __name__ == "__main__":
    main()
