from __future__ import annotations

import json
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from packaging_ai.api.schemas import JobRecord, JobStatus
from packaging_ai.config import JOB_STORE, SQL_CONNECTION
from packaging_ai.logutil import get_logger

log = get_logger("api.repository")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobRepository(ABC):
    @abstractmethod
    def ping(self) -> bool:
        ...

    @abstractmethod
    def ensure_schema(self) -> None:
        ...

    @abstractmethod
    def create_job(
        self,
        *,
        folder_path: str,
        output_dir: str | None,
        auto_confirm: bool,
    ) -> JobRecord:
        ...

    @abstractmethod
    def get_job(self, job_id: UUID) -> JobRecord | None:
        ...

    @abstractmethod
    def list_jobs(self, *, offset: int = 0, limit: int = 50) -> tuple[list[JobRecord], int]:
        ...

    @abstractmethod
    def update_job(
        self,
        job_id: UUID,
        *,
        status: JobStatus | None = None,
        confidence_score: float | None = None,
        state_json: dict[str, Any] | None = None,
        clarification_json: dict[str, Any] | None = None,
        error: str | None = None,
        clear_error: bool = False,
        clear_clarification: bool = False,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        set_started: bool = False,
        set_finished: bool = False,
    ) -> JobRecord | None:
        ...

    @abstractmethod
    def claim_next_queued(self) -> JobRecord | None:
        """Atomically claim one queued job → running."""
        ...

    @abstractmethod
    def add_event(self, job_id: UUID, event_type: str, message: str | None = None) -> None:
        ...


class MemoryJobRepository(JobRepository):
    """In-process store for local smoke tests (PACKAGING_AI_JOB_STORE=memory)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[UUID, JobRecord] = {}
        self._events: list[tuple[UUID, str, str | None, datetime]] = []

    def ping(self) -> bool:
        return True

    def ensure_schema(self) -> None:
        return

    def create_job(
        self,
        *,
        folder_path: str,
        output_dir: str | None,
        auto_confirm: bool,
    ) -> JobRecord:
        now = _utcnow()
        job = JobRecord(
            id=uuid.uuid4(),
            status="queued",
            folder_path=folder_path,
            output_dir=output_dir,
            auto_confirm=auto_confirm,
            state_json={},
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._events.append((job.id, "created", None, now))
        return job.model_copy(deep=True)

    def get_job(self, job_id: UUID) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def list_jobs(self, *, offset: int = 0, limit: int = 50) -> tuple[list[JobRecord], int]:
        with self._lock:
            ordered = sorted(
                self._jobs.values(), key=lambda j: j.created_at, reverse=True
            )
            total = len(ordered)
            page = [j.model_copy(deep=True) for j in ordered[offset : offset + limit]]
        return page, total

    def update_job(
        self,
        job_id: UUID,
        *,
        status: JobStatus | None = None,
        confidence_score: float | None = None,
        state_json: dict[str, Any] | None = None,
        clarification_json: dict[str, Any] | None = None,
        error: str | None = None,
        clear_error: bool = False,
        clear_clarification: bool = False,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        set_started: bool = False,
        set_finished: bool = False,
    ) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            data = job.model_dump()
            if status is not None:
                data["status"] = status
            if confidence_score is not None:
                data["confidence_score"] = confidence_score
            if state_json is not None:
                data["state_json"] = state_json
            if clear_clarification:
                data["clarification_json"] = None
            elif clarification_json is not None:
                data["clarification_json"] = clarification_json
            if clear_error:
                data["error"] = None
            elif error is not None:
                data["error"] = error
            if set_started:
                data["started_at"] = started_at or _utcnow()
            elif started_at is not None:
                data["started_at"] = started_at
            if set_finished:
                data["finished_at"] = finished_at or _utcnow()
            elif finished_at is not None:
                data["finished_at"] = finished_at
            data["updated_at"] = _utcnow()
            updated = JobRecord.model_validate(data)
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

    def claim_next_queued(self) -> JobRecord | None:
        with self._lock:
            candidates = [
                j for j in self._jobs.values() if j.status == "queued"
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda j: j.created_at)
            job = candidates[0]
            data = job.model_dump()
            data["status"] = "running"
            data["started_at"] = data.get("started_at") or _utcnow()
            data["updated_at"] = _utcnow()
            updated = JobRecord.model_validate(data)
            self._jobs[job.id] = updated
            self._events.append((job.id, "status_changed", "running", _utcnow()))
            return updated.model_copy(deep=True)

    def add_event(self, job_id: UUID, event_type: str, message: str | None = None) -> None:
        with self._lock:
            self._events.append((job_id, event_type, message, _utcnow()))


class SqlServerJobRepository(JobRepository):
    def __init__(self, connection_string: str) -> None:
        self._conn_str = connection_string
        self._lock = threading.Lock()

    def _connect(self):
        import pyodbc

        return pyodbc.connect(self._conn_str, autocommit=False)

    def ping(self) -> bool:
        try:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception as exc:
            log.warning("SQL ping failed: %s", exc)
            return False

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            # Execute as separate batches (GO-style); avoid splitting on every ";"
            cur.execute(
                """
IF OBJECT_ID(N'dbo.jobs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.jobs (
        id UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
        status NVARCHAR(32) NOT NULL,
        folder_path NVARCHAR(1024) NOT NULL,
        output_dir NVARCHAR(1024) NULL,
        auto_confirm BIT NOT NULL CONSTRAINT DF_jobs_auto_confirm DEFAULT (0),
        confidence_score FLOAT NULL,
        state_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_jobs_state_json DEFAULT (N'{}'),
        clarification_json NVARCHAR(MAX) NULL,
        error NVARCHAR(MAX) NULL,
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        started_at DATETIME2 NULL,
        finished_at DATETIME2 NULL
    );
    CREATE INDEX IX_jobs_status_created ON dbo.jobs (status, created_at);
END
                """
            )
            cur.execute(
                """
IF OBJECT_ID(N'dbo.job_events', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.job_events (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        job_id UNIQUEIDENTIFIER NOT NULL,
        event_type NVARCHAR(64) NOT NULL,
        message NVARCHAR(MAX) NULL,
        created_at DATETIME2 NOT NULL,
        CONSTRAINT FK_job_events_jobs FOREIGN KEY (job_id) REFERENCES dbo.jobs(id)
    );
    CREATE INDEX IX_job_events_job_created ON dbo.job_events (job_id, created_at);
END
                """
            )
            conn.commit()
        log.info("SQL schema ensured (jobs, job_events)")

    def create_job(
        self,
        *,
        folder_path: str,
        output_dir: str | None,
        auto_confirm: bool,
    ) -> JobRecord:
        job_id = uuid.uuid4()
        now = _utcnow()
        with self._lock:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO dbo.jobs (
                        id, status, folder_path, output_dir, auto_confirm,
                        state_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(job_id),
                        "queued",
                        folder_path,
                        output_dir,
                        1 if auto_confirm else 0,
                        "{}",
                        now,
                        now,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO dbo.job_events (job_id, event_type, message, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(job_id), "created", None, now),
                )
                conn.commit()
        return JobRecord(
            id=job_id,
            status="queued",
            folder_path=folder_path,
            output_dir=output_dir,
            auto_confirm=auto_confirm,
            state_json={},
            created_at=now,
            updated_at=now,
        )

    def _row_to_job(self, row) -> JobRecord:
        state_raw = row.state_json or "{}"
        clar_raw = row.clarification_json
        return JobRecord(
            id=UUID(str(row.id)),
            status=row.status,
            folder_path=row.folder_path,
            output_dir=row.output_dir,
            auto_confirm=bool(row.auto_confirm),
            confidence_score=row.confidence_score,
            state_json=json.loads(state_raw) if isinstance(state_raw, str) else (state_raw or {}),
            clarification_json=(
                json.loads(clar_raw)
                if isinstance(clar_raw, str) and clar_raw
                else clar_raw
            ),
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    def get_job(self, job_id: UUID) -> JobRecord | None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, status, folder_path, output_dir, auto_confirm, confidence_score,
                       state_json, clarification_json, error,
                       created_at, updated_at, started_at, finished_at
                FROM dbo.jobs WHERE id = ?
                """,
                (str(job_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_job(row)

    def list_jobs(self, *, offset: int = 0, limit: int = 50) -> tuple[list[JobRecord], int]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM dbo.jobs")
            total = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT id, status, folder_path, output_dir, auto_confirm, confidence_score,
                       state_json, clarification_json, error,
                       created_at, updated_at, started_at, finished_at
                FROM dbo.jobs
                ORDER BY created_at DESC
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
                """,
                (offset, limit),
            )
            rows = cur.fetchall()
            return [self._row_to_job(r) for r in rows], total

    def update_job(
        self,
        job_id: UUID,
        *,
        status: JobStatus | None = None,
        confidence_score: float | None = None,
        state_json: dict[str, Any] | None = None,
        clarification_json: dict[str, Any] | None = None,
        error: str | None = None,
        clear_error: bool = False,
        clear_clarification: bool = False,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        set_started: bool = False,
        set_finished: bool = False,
    ) -> JobRecord | None:
        sets: list[str] = ["updated_at = ?"]
        params: list[Any] = [_utcnow()]
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if confidence_score is not None:
            sets.append("confidence_score = ?")
            params.append(confidence_score)
        if state_json is not None:
            sets.append("state_json = ?")
            params.append(json.dumps(state_json))
        if clear_clarification:
            sets.append("clarification_json = NULL")
        elif clarification_json is not None:
            sets.append("clarification_json = ?")
            params.append(json.dumps(clarification_json))
        if clear_error:
            sets.append("error = NULL")
        elif error is not None:
            sets.append("error = ?")
            params.append(error)
        if set_started:
            sets.append("started_at = COALESCE(started_at, ?)")
            params.append(started_at or _utcnow())
        elif started_at is not None:
            sets.append("started_at = ?")
            params.append(started_at)
        if set_finished:
            sets.append("finished_at = ?")
            params.append(finished_at or _utcnow())
        elif finished_at is not None:
            sets.append("finished_at = ?")
            params.append(finished_at)
        params.append(str(job_id))
        with self._lock:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"UPDATE dbo.jobs SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                if status is not None:
                    cur.execute(
                        """
                        INSERT INTO dbo.job_events (job_id, event_type, message, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (str(job_id), "status_changed", status, _utcnow()),
                    )
                conn.commit()
        return self.get_job(job_id)

    def claim_next_queued(self) -> JobRecord | None:
        with self._lock:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT TOP (1) id
                    FROM dbo.jobs WITH (UPDLOCK, READPAST, ROWLOCK)
                    WHERE status = N'queued'
                    ORDER BY created_at ASC
                    """
                )
                row = cur.fetchone()
                if row is None:
                    conn.commit()
                    return None
                job_id = str(row[0])
                now = _utcnow()
                cur.execute(
                    """
                    UPDATE dbo.jobs
                    SET status = N'running',
                        started_at = COALESCE(started_at, ?),
                        updated_at = ?
                    WHERE id = ? AND status = N'queued'
                    """,
                    (now, now, job_id),
                )
                if cur.rowcount == 0:
                    conn.commit()
                    return None
                cur.execute(
                    """
                    INSERT INTO dbo.job_events (job_id, event_type, message, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (job_id, "status_changed", "running", now),
                )
                conn.commit()
        return self.get_job(UUID(job_id))

    def add_event(self, job_id: UUID, event_type: str, message: str | None = None) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO dbo.job_events (job_id, event_type, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(job_id), event_type, message, _utcnow()),
            )
            conn.commit()


_REPO: JobRepository | None = None


def get_repository() -> JobRepository:
    global _REPO
    if _REPO is not None:
        return _REPO
    if JOB_STORE == "memory":
        log.info("Using in-memory job store (PACKAGING_AI_JOB_STORE=memory)")
        _REPO = MemoryJobRepository()
        return _REPO
    if not SQL_CONNECTION:
        raise RuntimeError(
            "PACKAGING_AI_SQL_CONNECTION is required when job_store=sql "
            "(or set PACKAGING_AI_JOB_STORE=memory for local smoke tests)"
        )
    _REPO = SqlServerJobRepository(SQL_CONNECTION)
    return _REPO


def reset_repository_for_tests() -> None:
    global _REPO
    _REPO = None
