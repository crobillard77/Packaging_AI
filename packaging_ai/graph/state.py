from __future__ import annotations

from typing import Annotated, TypedDict

from packaging_ai.models import (
    DetectedInstaller,
    InstallPlan,
    PackageArtifacts,
    ReviewReport,
    VulnerabilityReport,
)


def _merge_clarifications(
    existing: list[str] | None,
    new: list[str] | None,
) -> list[str]:
    result = list(existing or [])
    for item in new or []:
        if item not in result:
            result.append(item)
    return result


class PackagingState(TypedDict, total=False):
    folder_path: str
    output_dir: str
    auto_confirm: bool
    user_confirmed: bool
    interactive: bool  # False for API: clarify pauses instead of input()
    awaiting_clarification: bool
    custom_requirements: str  # free-text operator requirements for LLM apply
    detected_installers: list[DetectedInstaller]
    install_plan: InstallPlan | None
    vulnerability_report: VulnerabilityReport | None
    review_findings: list[str]
    confidence_score: float
    user_clarifications: Annotated[list[str], _merge_clarifications]
    generated_artifacts: PackageArtifacts | None
    review_report: ReviewReport | None
    error: str | None
