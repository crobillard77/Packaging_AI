from __future__ import annotations

import threading
import time
from typing import Any
from uuid import UUID

from packaging_ai.api.repository import JobRepository, get_repository
from packaging_ai.api.state_codec import serialize_state
from packaging_ai.graph import run_packaging
from packaging_ai.graph.clarify_needs import clarification_needs
from packaging_ai.logutil import end_package_log, get_logger, setup_logging
from packaging_ai.config import LOG_FILE, LOG_LEVEL

log = get_logger("api.worker")


class JobWorker:
    """Background poller: claim queued jobs and run packaging (max 1 concurrent)."""

    def __init__(self, repo: JobRepository | None = None, poll_seconds: float = 1.0) -> None:
        self._repo = repo or get_repository()
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="packaging-ai-worker", daemon=True)
        self._thread.start()
        log.info("Job worker started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Job worker stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._busy.acquire(blocking=False):
                    try:
                        job = self._repo.claim_next_queued()
                        if job is not None:
                            self._run_job(job.id)
                    finally:
                        self._busy.release()
            except Exception:
                log.exception("Worker loop error")
            self._stop.wait(self._poll)

    def _run_job(self, job_id: UUID) -> None:
        job = self._repo.get_job(job_id)
        if job is None:
            return
        # Cancelled while queued → claimed race
        if job.status == "cancelled":
            return

        setup_logging(LOG_LEVEL, log_file=LOG_FILE, console=True)
        log.info("Running job %s folder=%s", job_id, job.folder_path)

        state_blob = job.state_json or {}
        clarifications = list(state_blob.get("user_clarifications") or [])
        user_confirmed = bool(state_blob.get("user_confirmed"))
        custom_requirements = str(state_blob.get("custom_requirements") or "")

        try:
            result = run_packaging(
                folder_path=job.folder_path,
                output_dir=job.output_dir,
                auto_confirm=job.auto_confirm,
                interactive=False,
                user_clarifications=clarifications,
                user_confirmed=user_confirmed,
                custom_requirements=custom_requirements,
            )
        except Exception as exc:
            log.exception("Job %s failed: %s", job_id, exc)
            end_package_log()
            self._repo.update_job(
                job_id,
                status="failed",
                error=str(exc),
                set_finished=True,
            )
            return

        # Re-check cancel
        latest = self._repo.get_job(job_id)
        if latest and latest.status == "cancelled":
            end_package_log()
            log.info("Job %s was cancelled; discarding result", job_id)
            return

        # Never drop clarifications / custom_requirements when persisting graph output.
        merged_clarifications = list(result.get("user_clarifications") or [])
        for item in clarifications:
            if item not in merged_clarifications:
                merged_clarifications.append(item)
        result["user_clarifications"] = merged_clarifications
        if custom_requirements and not (result.get("custom_requirements") or "").strip():
            result["custom_requirements"] = custom_requirements

        # Keep state confidence aligned with Review_Report.json.
        from packaging_ai.graph.clarify_needs import effective_confidence

        report = result.get("review_report")
        if report is not None:
            result["confidence_score"] = float(report.confidence_score)

        state_json = serialize_state(result)
        confidence = effective_confidence(result)
        needs = clarification_needs(result)

        if result.get("awaiting_clarification"):
            self._repo.update_job(
                job_id,
                status="awaiting_clarification",
                confidence_score=confidence,
                state_json=state_json,
                clarification_json=needs,
                clear_error=True,
            )
            self._repo.add_event(job_id, "awaiting_clarification", None)
            end_package_log()
            log.info("Job %s awaiting clarification", job_id)
            return

        if result.get("error"):
            self._repo.update_job(
                job_id,
                status="failed",
                confidence_score=confidence,
                state_json=state_json,
                clarification_json=needs,
                error=str(result.get("error")),
                set_finished=True,
            )
            end_package_log()
            log.error("Job %s failed: %s", job_id, result.get("error"))
            return

        artifacts = result.get("generated_artifacts")
        if artifacts is None:
            self._repo.update_job(
                job_id,
                status="failed",
                confidence_score=confidence,
                state_json=state_json,
                error="Packaging finished without artifacts",
                set_finished=True,
            )
            end_package_log()
            return

        self._repo.update_job(
            job_id,
            status="succeeded",
            confidence_score=confidence,
            state_json=state_json,
            clear_clarification=True,
            clear_error=True,
            set_finished=True,
        )
        self._repo.add_event(job_id, "succeeded", None)
        end_package_log()
        log.info("Job %s succeeded", job_id)


_WORKER: JobWorker | None = None


def get_worker() -> JobWorker:
    global _WORKER
    if _WORKER is None:
        _WORKER = JobWorker()
    return _WORKER
