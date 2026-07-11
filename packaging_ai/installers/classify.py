from __future__ import annotations

from pathlib import Path

from packaging_ai.models import InstallerFamily

# Byte signatures commonly embedded in installer EXEs
_SIGNATURES: list[tuple[InstallerFamily, tuple[bytes, ...]]] = [
    (InstallerFamily.INNO_SETUP, (b"Inno Setup", b"InnoSetup")),
    (InstallerFamily.NSIS, (b"Nullsoft Install System", b"Nullsoft")),
    (InstallerFamily.INSTALLSHIELD, (b"InstallShield", b"Installshield")),
    (InstallerFamily.WIX_BURN, (b"wix burn", b"Burn v", b".wixburn")),
    (InstallerFamily.ADVANCED_INSTALLER, (b"Advanced Installer",)),
    (InstallerFamily.SQUIRREL, (b"Squirrel", b"Update.exe")),
    (InstallerFamily.INSTALL4J, (b"install4j", b"com.install4j")),
]


def classify_exe(path: str | Path, max_bytes: int = 4_000_000) -> InstallerFamily:
    """Heuristic EXE family detection from embedded strings (FR-3)."""
    data = Path(path).read_bytes()[:max_bytes]
    # Case-insensitive search via lowercased haystack for ASCII markers
    haystack = data.lower()
    for family, markers in _SIGNATURES:
        for marker in markers:
            if marker.lower() in haystack:
                return family
    return InstallerFamily.UNKNOWN_EXE


def classify_by_extension(path: str | Path) -> InstallerFamily:
    ext = Path(path).suffix.lower()
    if ext == ".msi":
        return InstallerFamily.MSI
    if ext == ".mst":
        return InstallerFamily.MST
    if ext == ".exe":
        return classify_exe(path)
    return InstallerFamily.OTHER
