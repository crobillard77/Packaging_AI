from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


JobStatus = Literal[
    "queued",
    "running",
    "awaiting_clarification",
    "succeeded",
    "failed",
    "cancelled",
]


class CreateJobRequest(BaseModel):
    folder_path: str = Field(..., description="Absolute path to installer media folder")
    output_dir: str | None = Field(
        default=None, description="Optional absolute output root override"
    )
    auto_confirm: bool = Field(
        default=False,
        description="Skip soft low-confidence confirm only (cannot skip META/uninstall)",
    )


class CreateJobResponse(BaseModel):
    id: UUID
    status: JobStatus
    created_at: datetime


class ClarificationNeeded(BaseModel):
    needs_meta: bool = False
    needs_uninstall: bool = False
    needs_soft_confirm: bool = False
    suggested_uninstall: str | None = None
    open_questions: list[str] = Field(default_factory=list)


class PlanSummary(BaseModel):
    app_vendor: str = ""
    app_name: str = ""
    app_version: str = ""
    primary_family: str | None = None
    model: str | None = None
    reviewer: str | None = None


class JobResponse(BaseModel):
    id: UUID
    status: JobStatus
    folder_path: str
    output_dir: str | None = None
    auto_confirm: bool = False
    confidence_score: float | None = None
    review_findings: list[str] = Field(default_factory=list)
    clarification_needed: ClarificationNeeded | None = None
    plan_summary: PlanSummary | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    offset: int
    limit: int


class ClarifyRequest(BaseModel):
    action: Literal["submit", "abort"] = "submit"
    meta: str | None = Field(
        default=None, description="Publisher|AppName|Version (with or without META:)"
    )
    uninstall_command: str | None = Field(
        default=None, description="Already-normalized Execute-Process / Execute-MSI uninstall"
    )
    uninstall_paste: str | None = Field(
        default=None,
        description='Raw paste e.g. "C:\\Program Files\\App\\uninstall.exe" /S',
    )
    confirm: bool = False
    abort: bool = False


class ArtifactsResponse(BaseModel):
    package_dir: str | None = None
    deploy_script: str | None = None
    logs_dir: str | None = None
    install_plan_path: str | None = None
    review_path: str | None = None
    requirements_path: str | None = None
    vulnerability_path: str | None = None
    packaging_log_path: str | None = None
    footprint_mst_path: str | None = None


class LogFileInfo(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime | None = None


class LogListResponse(BaseModel):
    logs_dir: str
    files: list[LogFileInfo] = Field(default_factory=list)


class LogContentResponse(BaseModel):
    name: str
    content: str
    truncated: bool = False
    size_bytes: int


class HealthResponse(BaseModel):
    status: str
    version: str
    job_store: str
    sql_ok: bool | None = None
    detail: str | None = None


class JobRecord(BaseModel):
    """Internal job row (repository)."""

    id: UUID
    status: JobStatus
    folder_path: str
    output_dir: str | None = None
    auto_confirm: bool = False
    confidence_score: float | None = None
    state_json: dict[str, Any] = Field(default_factory=dict)
    clarification_json: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
