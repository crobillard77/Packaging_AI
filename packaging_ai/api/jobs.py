from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from packaging_ai.api.auth import require_api_key
from packaging_ai.api.repository import get_repository
from packaging_ai.api.schemas import (
    ArtifactsResponse,
    ClarificationNeeded,
    ClarifyRequest,
    CreateJobRequest,
    CreateJobResponse,
    JobListResponse,
    JobRecord,
    JobResponse,
    LogContentResponse,
    LogFileInfo,
    LogListResponse,
    PlanSummary,
)
from packaging_ai.api.state_codec import deserialize_state
from packaging_ai.models import PackageArtifacts
from packaging_ai.psadt.requirements import (
    exe_metadata_incomplete,
    is_valid_uninstall,
    normalize_uninstall_command,
    parse_meta_clarification,
)

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

# Max characters returned when viewing a log in the UI.
_LOG_VIEW_MAX_BYTES = 2 * 1024 * 1024


def _artifacts_for_job(job: JobRecord) -> PackageArtifacts | None:
    state = deserialize_state(job.state_json)
    artifacts = state.get("generated_artifacts")
    if artifacts is None:
        return None
    if not isinstance(artifacts, PackageArtifacts):
        return PackageArtifacts.model_validate(artifacts)
    return artifacts


def _logs_dir_for_job(job: JobRecord) -> Path:
    artifacts = _artifacts_for_job(job)
    if artifacts is None or not artifacts.logs_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No logs directory for this job",
        )
    logs_dir = Path(artifacts.logs_dir)
    if not logs_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Logs directory not found: {artifacts.logs_dir}",
        )
    return logs_dir.resolve()


def _safe_log_file(logs_dir: Path, name: str) -> Path:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid log file name",
        )
    candidate = (logs_dir / name).resolve()
    try:
        candidate.relative_to(logs_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Log file path escapes logs directory",
        ) from exc
    if not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log file not found: {name}",
        )
    return candidate


def _to_response(job: JobRecord) -> JobResponse:
    state = deserialize_state(job.state_json)
    plan = state.get("install_plan")
    plan_summary = None
    if plan is not None:
        plan_summary = PlanSummary(
            app_vendor=plan.app_vendor,
            app_name=plan.app_name,
            app_version=plan.app_version,
            primary_family=plan.primary_family.value if plan.primary_family else None,
            model=plan.model,
            reviewer=plan.reviewer,
        )
    clar = None
    confidence = job.confidence_score
    if job.status == "awaiting_clarification":
        # Recompute from state so soft-confirm matches Review_Report confidence.
        from packaging_ai.graph.clarify_needs import clarification_needs, effective_confidence

        needs = clarification_needs(state)
        clar = ClarificationNeeded.model_validate(needs)
        confidence = effective_confidence(state)
    findings = list(state.get("review_findings") or [])
    return JobResponse(
        id=job.id,
        status=job.status,
        folder_path=job.folder_path,
        output_dir=job.output_dir,
        auto_confirm=job.auto_confirm,
        confidence_score=confidence,
        review_findings=findings,
        clarification_needed=clar,
        plan_summary=plan_summary,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    body: CreateJobRequest,
    _: Annotated[str, Depends(require_api_key)],
) -> CreateJobResponse:
    folder = Path(body.folder_path)
    if not folder.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="folder_path must be absolute",
        )
    if not folder.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"folder_path not found or not a directory: {body.folder_path}",
        )
    output_dir = body.output_dir
    if output_dir is not None:
        out = Path(output_dir)
        if not out.is_absolute():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="output_dir must be absolute when provided",
            )

    repo = get_repository()
    custom = (body.custom_requirements or "").strip()
    initial_state: dict = {}
    if custom:
        initial_state["custom_requirements"] = custom
    job = repo.create_job(
        folder_path=str(folder),
        output_dir=output_dir,
        auto_confirm=body.auto_confirm,
        state_json=initial_state or None,
    )
    return CreateJobResponse(id=job.id, status=job.status, created_at=job.created_at)


@router.get("", response_model=JobListResponse)
def list_jobs(
    _: Annotated[str, Depends(require_api_key)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> JobListResponse:
    repo = get_repository()
    items, total = repo.list_jobs(offset=offset, limit=limit)
    return JobListResponse(
        items=[_to_response(j) for j in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: UUID,
    _: Annotated[str, Depends(require_api_key)],
) -> JobResponse:
    job = get_repository().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _to_response(job)


@router.get("/{job_id}/artifacts", response_model=ArtifactsResponse)
def get_artifacts(
    job_id: UUID,
    _: Annotated[str, Depends(require_api_key)],
) -> ArtifactsResponse:
    job = get_repository().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    artifacts = _artifacts_for_job(job)
    if artifacts is None:
        return ArtifactsResponse()
    return ArtifactsResponse(
        package_dir=artifacts.package_dir or None,
        deploy_script=artifacts.deploy_script or None,
        logs_dir=artifacts.logs_dir or None,
        install_plan_path=artifacts.install_plan_path or None,
        review_path=artifacts.review_path or None,
        requirements_path=artifacts.requirements_path or None,
        vulnerability_path=artifacts.vulnerability_path or None,
        packaging_log_path=artifacts.packaging_log_path or None,
        footprint_mst_path=artifacts.footprint_mst_path or None,
    )


@router.get("/{job_id}/logs", response_model=LogListResponse)
def list_logs(
    job_id: UUID,
    _: Annotated[str, Depends(require_api_key)],
) -> LogListResponse:
    job = get_repository().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    logs_dir = _logs_dir_for_job(job)
    files: list[LogFileInfo] = []
    for path in sorted(logs_dir.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        stat = path.stat()
        modified = None
        try:
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            modified = None
        files.append(
            LogFileInfo(
                name=path.name,
                size_bytes=stat.st_size,
                modified_at=modified,
            )
        )
    return LogListResponse(logs_dir=str(logs_dir), files=files)


@router.get("/{job_id}/logs/{file_name}", response_model=LogContentResponse)
def get_log_content(
    job_id: UUID,
    file_name: str,
    _: Annotated[str, Depends(require_api_key)],
) -> LogContentResponse:
    job = get_repository().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    logs_dir = _logs_dir_for_job(job)
    path = _safe_log_file(logs_dir, file_name)
    size = path.stat().st_size
    raw = path.read_bytes()[:_LOG_VIEW_MAX_BYTES]
    truncated = size > len(raw)
    content = raw.decode("utf-8", errors="replace")
    return LogContentResponse(
        name=path.name,
        content=content,
        truncated=truncated,
        size_bytes=size,
    )


@router.post("/{job_id}/clarify", response_model=JobResponse)
def clarify_job(
    job_id: UUID,
    body: ClarifyRequest,
    _: Annotated[str, Depends(require_api_key)],
) -> JobResponse:
    repo = get_repository()
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if body.abort or body.action == "abort":
        if job.status not in {"queued", "awaiting_clarification", "running"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot abort job in status {job.status}",
            )
        updated = repo.update_job(job_id, status="cancelled", set_finished=True)
        repo.add_event(job_id, "cancelled", "abort via clarify")
        assert updated is not None
        return _to_response(updated)

    if job.status != "awaiting_clarification":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is not awaiting clarification (status={job.status})",
        )

    state = deserialize_state(job.state_json)
    clarifications = list(state.get("user_clarifications") or [])
    user_confirmed = bool(state.get("user_confirmed"))
    plan = state.get("install_plan")
    needs = job.clarification_json or {}

    if body.meta:
        raw = body.meta.strip()
        if raw.upper().startswith("META:"):
            raw = raw[5:].strip()
        meta = parse_meta_clarification(f"META:{raw}")
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid meta; expected Publisher|AppName|Version",
            )
        vendor, name, version = meta
        clarifications.append(f"META:{vendor}|{name}|{version}")

    if body.uninstall_command or body.uninstall_paste:
        if body.uninstall_command:
            normalized = body.uninstall_command.strip()
        else:
            paste = (body.uninstall_paste or "").strip()
            if paste.lower() in {"suggest", "s"} and plan and plan.suggested_uninstall:
                normalized = plan.suggested_uninstall
            else:
                if "|" in paste and "Execute-" not in paste:
                    path_part, args_part = paste.split("|", 1)
                    paste = f'"{path_part.strip()}" {args_part.strip()}'
                normalized = normalize_uninstall_command(paste)
        if not is_valid_uninstall(normalized):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid uninstall command",
            )
        clarifications.append(f"UNINSTALL_CMD:{normalized}")

    if body.confirm:
        if needs.get("needs_meta") and not body.meta:
            if plan is not None and exe_metadata_incomplete(plan):
                already = any(parse_meta_clarification(c) for c in clarifications)
                if not already:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot confirm: META is still required",
                    )
        if needs.get("needs_uninstall") and not (
            body.uninstall_command or body.uninstall_paste
        ):
            already_u = any(c.startswith("UNINSTALL_CMD:") for c in clarifications)
            if not already_u:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot confirm: uninstall is still required",
                )
        user_confirmed = True
        clarifications.append("User confirmed current plan despite low confidence.")

    if body.custom_answers and body.custom_answers.strip():
        from packaging_ai.planning.custom_requirements import CUSTOM_REQ_PREFIX

        clarifications.append(f"{CUSTOM_REQ_PREFIX}{body.custom_answers.strip()}")

    if needs.get("needs_custom_clarify"):
        already_custom = any(c.startswith("CUSTOM_REQ:") for c in clarifications)
        if not already_custom:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="custom_answers are required for open custom-requirement questions",
            )

    state["user_clarifications"] = clarifications
    state["user_confirmed"] = user_confirmed
    state["awaiting_clarification"] = False

    from packaging_ai.api.state_codec import serialize_state

    updated = repo.update_job(
        job_id,
        status="queued",
        state_json=serialize_state(state),
        clear_clarification=True,
        clear_error=True,
    )
    repo.add_event(job_id, "clarify_received", None)
    assert updated is not None
    return _to_response(updated)


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: UUID,
    _: Annotated[str, Depends(require_api_key)],
) -> JobResponse:
    repo = get_repository()
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status in {"succeeded", "failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job already terminal ({job.status})",
        )
    updated = repo.update_job(job_id, status="cancelled", set_finished=True)
    repo.add_event(job_id, "cancelled", None)
    assert updated is not None
    return _to_response(updated)
