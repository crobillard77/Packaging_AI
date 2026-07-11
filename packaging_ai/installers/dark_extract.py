"""Extract embedded MSI packages from EXE installers using WiX dark.exe."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from packaging_ai.config import DARK_EXE, DARK_CACHE_DIR


@dataclass
class DarkExtractResult:
    success: bool
    source_exe: str
    msi_paths: list[str] = field(default_factory=list)
    extract_dir: str | None = None
    message: str = ""


def try_extract_msi_with_dark(exe_path: str | Path) -> DarkExtractResult:
    """Run WiX dark.exe on an EXE (Burn bundle) and collect extracted .msi files.

    Non-Burn EXEs (NSIS, Inno, etc.) fail with DARK0339 — that is expected;
    the caller should fall back to EXE packaging.
    """
    exe = Path(exe_path).resolve()
    if not exe.is_file():
        return DarkExtractResult(False, str(exe), message=f"EXE not found: {exe}")
    if not DARK_EXE.is_file():
        return DarkExtractResult(
            False,
            str(exe),
            message=f"dark.exe not found at {DARK_EXE}",
        )

    digest = hashlib.sha1(str(exe).encode("utf-8", errors="replace")).hexdigest()[:12]
    work = DARK_CACHE_DIR / f"{exe.stem}_{digest}"
    extract_dir = work / "extract"
    wxs_out = work / f"{exe.stem}.wxs"

    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(DARK_EXE),
        "-nologo",
        "-x",
        str(extract_dir),
        "-out",
        str(wxs_out),
        str(exe),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DarkExtractResult(
            False, str(exe), message="dark.exe timed out while decompiling the EXE."
        )
    except OSError as exc:
        return DarkExtractResult(False, str(exe), message=f"Failed to run dark.exe: {exc}")

    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
    if proc.returncode != 0:
        # Common: DARK0339 — not a WiX Burn stub
        return DarkExtractResult(
            False,
            str(exe),
            extract_dir=str(extract_dir),
            message=combined or f"dark.exe exited with code {proc.returncode}",
        )

    msis = sorted(extract_dir.rglob("*.msi"), key=lambda p: (-p.stat().st_size, p.name.lower()))
    if not msis:
        return DarkExtractResult(
            False,
            str(exe),
            extract_dir=str(extract_dir),
            message="dark.exe succeeded but no .msi files were extracted.",
        )

    return DarkExtractResult(
        True,
        str(exe),
        msi_paths=[str(p.resolve()) for p in msis],
        extract_dir=str(extract_dir),
        message=f"Extracted {len(msis)} MSI file(s) via dark.exe.",
    )


def select_main_msi(msi_paths: list[str]) -> str | None:
    """Prefer the largest extracted MSI as the main installer."""
    if not msi_paths:
        return None
    return max(msi_paths, key=lambda p: Path(p).stat().st_size if Path(p).is_file() else 0)
