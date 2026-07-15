from __future__ import annotations

from typing import Any

from packaging_ai.graph.state import PackagingState
from packaging_ai.models import (
    DetectedInstaller,
    InstallPlan,
    PackageArtifacts,
    ReviewReport,
    VulnerabilityReport,
)


def serialize_state(state: PackagingState) -> dict[str, Any]:
    """JSON-friendly dump of PackagingState for SQL state_json."""
    out: dict[str, Any] = {}
    for key, value in dict(state).items():
        if value is None:
            out[key] = None
        elif hasattr(value, "model_dump"):
            out[key] = value.model_dump(mode="json")
        elif isinstance(value, list) and value and hasattr(value[0], "model_dump"):
            out[key] = [item.model_dump(mode="json") for item in value]
        else:
            out[key] = value
    return out


def deserialize_state(data: dict[str, Any] | None) -> PackagingState:
    if not data:
        return {}  # type: ignore[return-value]
    state: PackagingState = {}  # type: ignore[assignment]
    for key, value in data.items():
        if key == "detected_installers" and isinstance(value, list):
            state["detected_installers"] = [
                DetectedInstaller.model_validate(item) for item in value
            ]
        elif key == "install_plan" and value is not None:
            state["install_plan"] = InstallPlan.model_validate(value)
        elif key == "vulnerability_report" and value is not None:
            state["vulnerability_report"] = VulnerabilityReport.model_validate(value)
        elif key == "review_report" and value is not None:
            state["review_report"] = ReviewReport.model_validate(value)
        elif key == "generated_artifacts" and value is not None:
            state["generated_artifacts"] = PackageArtifacts.model_validate(value)
        else:
            state[key] = value  # type: ignore[literal-required]
    return state
