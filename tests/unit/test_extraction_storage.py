"""Bounded retrieval, deterministic artifacts and cleanup without external services."""

import hashlib
import os
from io import BytesIO
from unittest.mock import Mock

import pytest
from minio.error import S3Error

from apps.worker.extraction_config import ExtractionSettings
from apps.worker.extraction_process import ExtractionRequest, process_request
from packages.curriculum.pdf import extract_pdf
from packages.persistence.extractions import persist_extraction
from packages.persistence.object_storage import (
    ObjectIntegrityError,
    ObjectLimitError,
    ObjectStorage,
    ObjectStorageSettings,
)
from tests.pdf_fixtures import document_source, syllabus_pdf


class MemoryObjects:
    def __init__(self):
        self.objects = {}
        self.reads = []
        self.responses = []
        self.writes = 0
        self.write_failure = False

    def get_object(self, bucket, key):
        self.reads.append(key)
        if key not in self.objects:
            raise S3Error("NoSuchKey", "synthetic", key, "request", "host", None)
        stream = BytesIO(self.objects[key])
        response = Mock()

        def read(size):
            assert 0 < size <= 64 * 1024
            return stream.read(size)

        response.read.side_effect = read
        response.close.side_effect = stream.close
        self.responses.append(response)
        return response

    def put_object(self, bucket, key, stream, size, **kwargs):
        if self.write_failure:
            raise S3Error("ServiceUnavailable", "synthetic", key, "request", "host", None)
        self.objects[key] = stream.read(size)
        self.writes += 1


@pytest.fixture
def storage():
    store = ObjectStorage(ObjectStorageSettings("127.0.0.1:1", "test", "test", "test", False))
    store.client = MemoryObjects()
    yield store
    store.close_sync()


@pytest.fixture
def result():
    content = syllabus_pdf(["Module I: Basics\n1.1 Introduction\nBody paragraph"])
    return extract_pdf(BytesIO(content), document_source(content, 1), max_bytes=100000,
                       max_pages=2, max_output_bytes=100000, minimum_useful_characters=1)


def test_idempotent_artifact_reuse_and_document_version_identity(storage, result):
    reference = persist_extraction(storage, result, 100000)
    assert persist_extraction(storage, result, 100000) == reference
    assert storage.client.writes == 1
    assert reference == f"minio://test/{result.artifact_key()}"
    assert storage.client.objects[result.artifact_key()] == result.canonical_bytes()
    assert str(result.source.version_id) in reference
    assert result.schema_version in reference
    for response in storage.client.responses:
        response.close.assert_called_once()
        response.release_conn.assert_called_once()


def test_cross_document_or_version_does_not_overwrite(storage, result):
    from uuid import uuid4

    from packages.curriculum.structure import detect_structure

    first = persist_extraction(storage, result, 100000)
    original_bytes = result.canonical_bytes()
    for field in ["version_id", "document_id"]:
        source = result.source.model_copy(update={field: uuid4()})
        nodes, unclassified, warnings = detect_structure(source, result.pages)
        other = result.model_copy(update={"source": source, "nodes": nodes,
                                          "unclassified": unclassified, "warnings": warnings})
        assert persist_extraction(storage, other, 100000) != first
    assert len(storage.client.objects) == 3
    assert storage.client.objects[result.artifact_key()] == original_bytes


def test_existing_corrupt_artifact_is_never_overwritten(storage, result):
    storage.client.objects[result.artifact_key()] = b"corrupt"
    with pytest.raises(ObjectIntegrityError):
        persist_extraction(storage, result, 100000)
    assert storage.client.writes == 0


def test_failed_artifact_write_cannot_return_success(storage, result):
    storage.client.write_failure = True
    with pytest.raises(S3Error):
        persist_extraction(storage, result, 100000)
    assert not storage.client.objects


@pytest.mark.parametrize("failure", ["size", "hash", "limit", "read"])
def test_stream_integrity_limits_and_response_cleanup(storage, failure):
    content = b"synthetic content"
    storage.client.objects["source"] = content
    if failure == "read":
        original = storage.client.get_object

        def failing(*args):
            response = original(*args)
            response.read.side_effect = OSError("synthetic read error")
            return response

        storage.client.get_object = failing
    with pytest.raises((ObjectIntegrityError, ObjectLimitError, OSError)):
        storage.download_into(
            "source", BytesIO(), max_bytes=5 if failure == "limit" else 1000,
            expected_size=1 if failure in {"size", "limit"} else len(content),
            expected_sha256="0" * 64 if failure == "hash" else hashlib.sha256(content).hexdigest(),
        )
    response = storage.client.responses[-1]
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


@pytest.mark.parametrize("kind", ["valid", "malformed", "write_failure", "missing", "encrypted"])
def test_processing_closes_temporary_files_on_success_and_failure(storage, monkeypatch, kind):
    import apps.worker.extraction_process as module

    content = (b"%PDF-1.7\ninvalid" if kind == "malformed" else
               syllabus_pdf(["Unit 1: Introduction"], encrypted=kind == "encrypted"))
    if kind != "missing":
        storage.client.objects["trusted-key"] = content
    storage.client.write_failure = kind == "write_failure"
    monkeypatch.setattr(module, "ObjectStorage", lambda settings: storage)
    files = []
    original = module.tempfile.TemporaryFile

    def record(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(module.tempfile, "TemporaryFile", record)
    request = ExtractionRequest(
        source=document_source(content, 1), object_key="trusted-key",
        storage=ObjectStorageSettings("127.0.0.1:1", "test", "test", "test", False),
        limits=ExtractionSettings(_env_file=None), max_pdf_bytes=100000,
        max_pdf_pages=5, parent_pid=os.getpid(),
    )
    outcome = process_request(request)
    assert all(file.closed for file in files) and files
    if kind == "valid":
        assert outcome.result_ref and not outcome.error_code
    else:
        assert outcome.result_ref is None
        assert outcome.error_code == {"malformed": "INVALID_PDF", "missing": "SOURCE_NOT_FOUND",
                                       "encrypted": "ENCRYPTED_PDF",
                                       "write_failure": "STORAGE_UNAVAILABLE"}[kind]
        assert outcome.retryable == (kind == "write_failure")
