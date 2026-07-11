from __future__ import annotations

from pathlib import Path

from packaging_ai.config import INSTALLER_EXTENSIONS


def scan_folder(folder_path: str | Path) -> list[str]:
    """Enumerate installer-related files under an absolute folder path (FR-1)."""
    root = Path(folder_path)
    if not root.is_absolute():
        raise ValueError(f"Folder path must be absolute: {folder_path}")
    if not root.is_dir():
        raise FileNotFoundError(f"Folder does not exist or is not a directory: {folder_path}")

    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in INSTALLER_EXTENSIONS:
            found.append(str(path.resolve()))
    return found
