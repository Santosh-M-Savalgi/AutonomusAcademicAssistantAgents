"""Tests for Background Jobs & Asynchronous Processing (Sprint 9).

Covers:
- Queue operations (enqueue, dequeue, state transitions)
- Retry logic (exponential backoff, dead-letter)
- Worker lifecycle (heartbeat, health checks)
- Job APIs (create, get, list, cancel, retry)
- Authorization
- Progress tracking
- Cancellation
- Concurrent execution
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs.models import (
    Job,
    JobPriority,
    JobProgress,
    JobStatus,
    JobType,
    RetryPolicy,
)
from app.jobs.queue import JobQueue
from app.jobs.scheduler import JobScheduler, ScheduledTask
from app.jobs.service import JobService
from app.jobs.tasks import (
    get_task_handler,
    parse_syllabus_task,
    recompute_embeddings_task,
)
from app.jobs.worker import WorkerPool


# ═══════════════════════════════════════════════════════════════════════════════
# Mock Redis (simplified for testing)
# ═══════════════════════════════════════════════════════════════════════════════


class MockRedis:
    """In-memory Redis mock for testing queue operations."""

    def __init__(self):
        self._data: dict[str, dict | set | list] = {}
        self._meta_data: dict[str, dict] = {}  # for meta hash keys

    def pipeline(self):
        return MockPipeline(self)

    async def hset(self, key: str, field_or_mapping: str | dict | None = None, value: str | None = None) -> int:
        """Simulate redis-py hset which supports both (key, mapping=...) and (key, field, value)."""
        if isinstance(field_or_mapping, dict):
            self._meta_data[key] = field_or_mapping
        elif isinstance(field_or_mapping, str) and value is not None:
            if key not in self._meta_data:
                self._meta_data[key] = {}
            self._meta_data[key][field_or_mapping] = value
        return 1

    async def hgetall(self, key: str) -> dict:
        return self._meta_data.get(key, {})

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def zadd(self, key: str, mapping: dict) -> int:
        if key not in self._data:
            self._data[key] = {}
        self._data[key].update(mapping)
        return len(mapping)

    async def zrem(self, key: str, *members: str) -> int:
        val = self._data.get(key, {})
        if isinstance(val, dict):
            count = 0
            for m in members:
                if m in val:
                    del val[m]
                    count += 1
            return count
        return 0

    async def zcard(self, key: str) -> int:
        val = self._data.get(key, {})
        if isinstance(val, dict):
            return len(val)
        return 0

    async def scard(self, key: str) -> int:
        val = self._data.get(key, set())
        if isinstance(val, set):
            return len(val)
        return 0

    async def sadd(self, key: str, *members: str) -> int:
        if key not in self._data:
            self._data[key] = set()
        s = self._data[key]
        if not isinstance(s, set):
            s = set()
        before = len(s)
        s.update(members)
        self._data[key] = s
        return len(s) - before

    async def srem(self, key: str, *members: str) -> int:
        s = self._data.get(key, set())
        if isinstance(s, set):
            count = 0
            for m in members:
                if m in s:
                    s.remove(m)
                    count += 1
            self._data[key] = s
            return count
        return 0

    async def lpush(self, key: str, *values: str) -> int:
        if key not in self._data:
            self._data[key] = []
        lst = self._data[key]
        if not isinstance(lst, list):
            lst = []
        for v in reversed(values):
            lst.insert(0, v)
        self._data[key] = lst
        return len(lst)

    async def llen(self, key: str) -> int:
        lst = self._data.get(key, [])
        if isinstance(lst, list):
            return len(lst)
        return 0

    async def eval(self, script: str, num_keys: int, *args) -> str | None:
        """Simplified eval for zrange + zrem pattern."""
        key = args[0]
        val = self._data.get(key, {})
        if isinstance(val, dict) and val:
            sorted_items = sorted(val.items(), key=lambda x: x[1])
            member = sorted_items[0][0]
            del val[member]
            return member
        return None

    async def scan(self, cursor: int, match: str = "*", count: int = 100) -> tuple[int, list[str]]:
        from fnmatch import fnmatch
        keys = [k for k in self._meta_data if fnmatch(k, match)]
        return 0, keys


class MockPipeline:
    """Mock Redis pipeline for testing."""

    def __init__(self, redis: MockRedis):
        self._redis = redis
        self._commands: list[tuple] = []

    def hset(self, key: str, mapping: dict | None = None, **kwargs) -> "MockPipeline":
        self._commands.append(("hset", key, mapping or kwargs))
        return self

    def expire(self, key: str, seconds: int) -> "MockPipeline":
        self._commands.append(("expire", key, seconds))
        return self

    def zadd(self, key: str, mapping: dict) -> "MockPipeline":
        self._commands.append(("zadd", key, mapping))
        return self

    def sadd(self, key: str, *members: str) -> "MockPipeline":
        self._commands.append(("sadd", key, members))
        return self

    def srem(self, key: str, *members: str) -> "MockPipeline":
        self._commands.append(("srem", key, members))
        return self

    def zrem(self, key: str, *members: str) -> "MockPipeline":
        self._commands.append(("zrem", key, members))
        return self

    def lpush(self, key: str, *values: str) -> "MockPipeline":
        self._commands.append(("lpush", key, values))
        return self

    async def execute(self) -> list:
        results = []
        for cmd in self._commands:
            op = cmd[0]
            if op == "hset":
                r = await self._redis.hset(cmd[1], cmd[2])
                results.append(r)
            elif op == "expire":
                r = await self._redis.expire(cmd[1], cmd[2])
                results.append(r)
            elif op == "zadd":
                r = await self._redis.zadd(cmd[1], cmd[2])
                results.append(r)
            elif op == "sadd":
                r = await self._redis.sadd(cmd[1], *cmd[2])
                results.append(r)
            elif op == "srem":
                r = await self._redis.srem(cmd[1], *cmd[2])
                results.append(r)
            elif op == "zrem":
                r = await self._redis.zrem(cmd[1], *cmd[2])
                results.append(r)
            elif op == "lpush":
                r = await self._redis.lpush(cmd[1], *cmd[2])
                results.append(r)
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# Model Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestJobModel:
    """Test the Job domain model."""

    def test_job_defaults(self):
        """Job should have sensible defaults."""
        job = Job()
        assert job.status == JobStatus.QUEUED
        assert job.priority == JobPriority.DEFAULT
        assert job.retry_count == 0
        assert not job.is_terminal()

    def test_terminal_states(self):
        """COMPLETED, FAILED, and CANCELLED are terminal."""
        completed = Job(status=JobStatus.COMPLETED)
        failed = Job(status=JobStatus.FAILED)
        cancelled = Job(status=JobStatus.CANCELLED)
        queued = Job(status=JobStatus.QUEUED)
        assert completed.is_terminal()
        assert failed.is_terminal()
        assert cancelled.is_terminal()
        assert not queued.is_terminal()

    def test_should_retry(self):
        """Should return True when failed and under max retries."""
        job = Job(status=JobStatus.FAILED, retry_count=1, max_retries=3)
        assert job.should_retry()
        job2 = Job(status=JobStatus.FAILED, retry_count=3, max_retries=3)
        assert not job2.should_retry()
        job3 = Job(status=JobStatus.COMPLETED, retry_count=1, max_retries=3)
        assert not job3.should_retry()

    def test_all_enums(self):
        """All job statuses are defined."""
        assert len(JobStatus) == 6
        assert len(JobType) >= 10
        assert len(JobPriority) == 4

    def test_retry_policy_delay(self):
        """Exponential backoff should increase delay."""
        policy = RetryPolicy(base_delay_seconds=5.0, backoff_multiplier=2.0)
        assert policy.delay_for_attempt(0) == 5.0
        assert policy.delay_for_attempt(1) == 10.0
        assert policy.delay_for_attempt(2) == 20.0

    def test_retry_policy_max_delay(self):
        """Delay should be capped at max_delay_seconds."""
        policy = RetryPolicy(base_delay_seconds=1000.0, backoff_multiplier=10.0, max_delay_seconds=3600.0)
        assert policy.delay_for_attempt(3) == 3600.0

    def test_job_progress_default(self):
        """JobProgress should have sensible defaults."""
        p = JobProgress()
        assert p.percentage == 0.0
        assert p.current_stage == "initializing"

    def test_job_progress_custom(self):
        """JobProgress should accept custom values."""
        p = JobProgress(percentage=75.0, current_stage="embedding", message="Processing...", estimated_remaining_seconds=120.0)
        assert p.percentage == 75.0
        assert p.estimated_remaining_seconds == 120.0


# ═══════════════════════════════════════════════════════════════════════════════
# Queue Tests (all async)
# ═══════════════════════════════════════════════════════════════════════════════


class TestJobQueue:
    """Test Redis-backed job queue operations."""

    @pytest.fixture
    def redis(self):
        return MockRedis()

    @pytest.fixture
    def queue(self, redis):
        return JobQueue(redis)

    @pytest.mark.asyncio
    async def test_enqueue(self, queue):
        """Enqueue should store job metadata and add to sorted set."""
        job = Job(job_type=JobType.PARSE_SYLLABUS)
        result = await queue.enqueue(job)
        assert result.status == JobStatus.QUEUED
        assert result.job_id is not None
        stored = await queue.get_job(job.job_id)
        assert stored is not None
        assert stored.job_type == job.job_type

    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(self, queue):
        """Dequeue should retrieve the highest-priority job."""
        job = Job(job_type=JobType.PARSE_SYLLABUS)
        await queue.enqueue(job)
        dequeued = await queue.dequeue("test-worker")
        assert dequeued is not None
        assert dequeued.job_id == job.job_id
        consumed = await queue.dequeue("test-worker")
        assert consumed is None

    @pytest.mark.asyncio
    async def test_priority_ordering(self, queue):
        """Higher-priority jobs should be dequeued first."""
        low = Job(job_type=JobType.PARSE_SYLLABUS, priority=JobPriority.LOW)
        high = Job(job_type=JobType.COMPUTE_ANALYTICS, priority=JobPriority.CRITICAL)
        await queue.enqueue(low)
        await queue.enqueue(high)
        first = await queue.dequeue("test-worker")
        assert first is not None
        assert first.priority == JobPriority.CRITICAL
        second = await queue.dequeue("test-worker")
        assert second is not None
        assert second.priority == JobPriority.LOW

    @pytest.mark.asyncio
    async def test_start_complete_job(self, queue):
        """Start and complete a job should update its state."""
        job = Job(job_type=JobType.PARSE_SYLLABUS)
        await queue.enqueue(job)
        started = await queue.start_job(job.job_id, "worker-1")
        assert started is not None
        assert started.status == JobStatus.RUNNING
        assert started.worker_id == "worker-1"
        completed = await queue.complete_job(job.job_id, {"result": "ok"})
        assert completed is not None
        assert completed.status == JobStatus.COMPLETED
        assert completed.result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_fail_and_retry(self, queue):
        """Failed job should be moved to retry queue."""
        job = Job(job_type=JobType.PARSE_SYLLABUS, max_retries=3)
        await queue.enqueue(job)
        await queue.start_job(job.job_id, "worker-1")
        failed = await queue.fail_job(job.job_id, "Something went wrong")
        assert failed is not None
        assert failed.status == JobStatus.RETRYING
        assert failed.retry_count == 1
        assert "Something went wrong" in (failed.error_message or "")

    @pytest.mark.asyncio
    async def test_permanent_failure_dead_letter(self, queue):
        """Maxed-out retries should move to dead-letter (FAILED)."""
        job = Job(job_type=JobType.PARSE_SYLLABUS, max_retries=2, retry_count=2)
        await queue.enqueue(job)
        await queue.start_job(job.job_id, "worker-1")
        failed = await queue.fail_job(job.job_id, "Last attempt failed")
        assert failed is not None
        assert failed.status == JobStatus.FAILED
        assert failed.retry_count == 3

    @pytest.mark.asyncio
    async def test_cancel_queued_job(self, queue):
        """Queued jobs should be cancellable."""
        job = Job(job_type=JobType.PARSE_SYLLABUS)
        await queue.enqueue(job)
        cancelled = await queue.cancel_job(job.job_id)
        assert cancelled is not None
        assert cancelled.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_update_progress(self, queue):
        """Progress updates should be stored."""
        job = Job(job_type=JobType.PARSE_SYLLABUS)
        await queue.enqueue(job)
        await queue.start_job(job.job_id, "worker-1")
        progress = JobProgress(percentage=50.0, current_stage="parsing", message="Halfway there")
        updated = await queue.update_progress(job.job_id, progress)
        assert updated is not None
        assert updated.progress.percentage == 50.0

    @pytest.mark.asyncio
    async def test_count_by_status(self, queue):
        """Count by status should return correct counts."""
        counts = await queue.count_by_status()
        assert isinstance(counts, dict)
        assert "queued" in counts


# ═══════════════════════════════════════════════════════════════════════════════
# Service Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestJobService:
    """Test job service orchestration."""

    @pytest.fixture
    def service(self):
        redis = MockRedis()
        queue = JobQueue(redis)
        return JobService(queue)

    @pytest.mark.asyncio
    async def test_create_job(self, service):
        """Creating a job should enqueue it."""
        job = await service.create_job(
            job_type=JobType.PARSE_SYLLABUS,
            user_id=uuid.uuid4(),
            payload={"syllabus_id": "test"},
        )
        assert job.status == JobStatus.QUEUED
        assert job.job_type == JobType.PARSE_SYLLABUS

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, service):
        """Getting a non-existent job should return None."""
        result = await service.get_job(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_authorization(self, service):
        """Users should only see their own jobs."""
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()
        job = await service.create_job(JobType.PARSE_SYLLABUS, user_id=user1)
        result = await service.get_job(job.job_id, user1)
        assert result is not None
        with pytest.raises(PermissionError):
            await service.get_job(job.job_id, user2)
        result = await service.get_job(job.job_id, user2, is_admin=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_cancel_job_authorization(self, service):
        """Users should only cancel their own jobs."""
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()
        job = await service.create_job(JobType.PARSE_SYLLABUS, user_id=user1)
        with pytest.raises(PermissionError):
            await service.cancel_job(job.job_id, user2)
        cancelled = await service.cancel_job(job.job_id, user2, is_admin=True)
        assert cancelled.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_list_jobs_filter_by_user(self, service):
        """Students should only see their own jobs."""
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()
        await service.create_job(JobType.PARSE_SYLLABUS, user_id=user1)
        await service.create_job(JobType.COMPUTE_ANALYTICS, user_id=user2)
        jobs1, total1 = await service.list_jobs(user1)
        assert total1 == 1
        jobs2, total2 = await service.list_jobs(user2)
        assert total2 == 1
        admin_jobs, admin_total = await service.list_jobs(user1, is_admin=True)
        assert admin_total == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Task Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTasks:
    """Test task registration and execution."""

    def test_register_task(self):
        """Registering a task should add it to the registry."""
        assert get_task_handler(JobType.PARSE_SYLLABUS) is not None
        assert get_task_handler(JobType.GENERATE_EMBEDDINGS) is not None
        assert get_task_handler(JobType.BUILD_KNOWLEDGE_GRAPH) is not None
        assert get_task_handler(JobType.INDEX_DOCUMENTS) is not None
        assert get_task_handler(JobType.COMPUTE_ANALYTICS) is not None

    def test_unregistered_task(self):
        """Unregistered task type should not raise error."""
        assert get_task_handler(JobType.NOTIFICATION) is not None

    @pytest.mark.asyncio
    async def test_parse_syllabus_task(self):
        """Parse syllabus task should progress and return result."""
        redis = MockRedis()
        queue = JobQueue(redis)
        job = Job(job_type=JobType.PARSE_SYLLABUS, payload={"syllabus_id": "test-123"})
        result = await parse_syllabus_task(job, queue)
        assert result["syllabus_id"] == "test-123"
        assert result["status"] == "parsed"

    @pytest.mark.asyncio
    async def test_recompute_embeddings_task(self):
        """Embedding task should report progress."""
        redis = MockRedis()
        queue = JobQueue(redis)
        job = Job(job_type=JobType.GENERATE_EMBEDDINGS, payload={"document_ids": ["doc1", "doc2", "doc3"]})
        result = await recompute_embeddings_task(job, queue)
        assert result["documents_embedded"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduler Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestScheduler:
    """Test job scheduler."""

    def test_scheduled_task_should_run(self):
        """Scheduled task should indicate when it should run."""
        task = ScheduledTask(name="Test Task", job_type=JobType.COMPUTE_ANALYTICS, cron_expression="daily @ 02:00")
        run_time = datetime(2026, 7, 18, 2, 0, tzinfo=timezone.utc)
        assert task.should_run(run_time)
        skip_time = datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc)
        assert not task.should_run(skip_time)
        task.mark_run(run_time)
        assert not task.should_run(run_time)

    def test_default_scheduled_tasks(self):
        """Default scheduled tasks should cover required maintenance."""
        from app.jobs.scheduler import DEFAULT_SCHEDULED_TASKS
        names = [t.name for t in DEFAULT_SCHEDULED_TASKS]
        assert "Nightly Analytics Refresh" in names
        assert "Recommendation Recalculation" in names
        assert "Inactive Learner Cleanup" in names
        assert "Expired Session Cleanup" in names
        assert "Old Checkpoint Cleanup" in names
        assert "Adaptive Data Rebuild" in names

    def test_add_remove_task(self):
        """Tasks should be addable and removable."""
        async def dummy_enqueue(job_type, payload, priority):
            pass
        scheduler = JobScheduler(dummy_enqueue)
        assert len(scheduler.tasks) == 6
        scheduler.add_task(ScheduledTask(name="Custom Task", job_type=JobType.NOTIFICATION, cron_expression="daily @ 10:00"))
        assert len(scheduler.tasks) == 7
        scheduler.remove_task("Custom Task")
        assert len(scheduler.tasks) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# Worker Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerPool:
    """Test worker pool lifecycle."""

    @pytest.fixture
    def worker(self):
        redis = MockRedis()
        queue = JobQueue(redis)
        service = JobService(queue)
        return WorkerPool(queue, service)

    def test_worker_id_property(self, worker):
        """Worker should have a unique ID."""
        assert worker.worker_id.startswith("worker-")
        assert len(worker.worker_id) > 12

    def test_uptime_when_not_started(self, worker):
        """Uptime should be 0 before start."""
        assert worker.uptime_seconds == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Retry Policy Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryPolicy:
    """Test retry policy edge cases."""

    def test_zero_retries(self):
        """Policy with max_retries=0 should never retry."""
        policy = RetryPolicy(max_retries=0)
        assert policy.delay_for_attempt(0) == 5.0
        assert policy.max_retries == 0

    def test_custom_backoff(self):
        """Custom backoff values should be respected."""
        policy = RetryPolicy(max_retries=5, base_delay_seconds=1.0, backoff_multiplier=3.0, max_delay_seconds=100.0)
        assert policy.delay_for_attempt(0) == 1.0
        assert policy.delay_for_attempt(1) == 3.0
        assert policy.delay_for_attempt(2) == 9.0
        assert policy.delay_for_attempt(3) == 27.0
        assert policy.delay_for_attempt(4) == 81.0
        assert policy.delay_for_attempt(5) == 100.0
