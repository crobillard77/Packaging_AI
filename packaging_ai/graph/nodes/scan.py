from __future__ import annotations

from pathlib import Path

from packaging_ai.config import PRIMARY_INSTALLER_EXTENSIONS
from packaging_ai.graph.state import PackagingState
from packaging_ai.installers import scan_folder
from packaging_ai.logutil import get_logger
from packaging_ai.models import DetectedInstaller

log = get_logger("graph.scan")


def scan_node(state: PackagingState) -> dict:
    folder = state["folder_path"]
    log.info("Scanning folder: %s", folder)
    paths = scan_folder(folder)
    detected = [
        DetectedInstaller(
            path=p,
            extension=Path(p).suffix.lower(),
            is_primary_candidate=Path(p).suffix.lower() in PRIMARY_INSTALLER_EXTENSIONS,
        )
        for p in paths
    ]
    log.info("Found %s installer media file(s)", len(detected))
    for item in detected:
        log.debug("Detected: %s (%s)", item.path, item.extension)
    return {"detected_installers": detected, "error": None}
