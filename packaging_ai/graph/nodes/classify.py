from __future__ import annotations

from pathlib import Path

from packaging_ai.graph.state import PackagingState
from packaging_ai.installers import classify_by_extension, log_param_for, silent_args_for
from packaging_ai.logutil import get_logger
from packaging_ai.models import DetectedInstaller, InstallerFamily
from packaging_ai.msi.reader import get_msi_library

log = get_logger("graph.classify")


def classify_node(state: PackagingState) -> dict:
    from packaging_ai.installers.dark_extract import select_main_msi, try_extract_msi_with_dark

    msi_lib = get_msi_library()
    updated: list[DetectedInstaller] = []
    for item in state.get("detected_installers") or []:
        family = classify_by_extension(item.path)
        notes = list(item.notes)
        msi_meta = None
        path = item.path
        extension = item.extension
        source_exe: str | None = None
        extracted_via_dark = False

        # EXE → try WiX dark.exe to find an embedded main MSI
        if extension == ".exe" and family != InstallerFamily.MSI:
            log.info("Trying dark.exe on %s...", Path(path).name)
            dark = try_extract_msi_with_dark(path)
            if dark.success and dark.msi_paths:
                main_msi = select_main_msi(dark.msi_paths)
                if main_msi:
                    source_exe = str(Path(path).resolve())
                    path = main_msi
                    extension = ".msi"
                    family = InstallerFamily.MSI
                    extracted_via_dark = True
                    notes.append(dark.message)
                    notes.append(f"Using main MSI extracted by dark.exe: {Path(main_msi).name}")
                    notes.append(f"Source EXE: {Path(source_exe).name}")
                    log.info("dark.exe found MSI: %s", Path(main_msi).name)
            else:
                brief = dark.message.splitlines()[0] if dark.message else "no MSI"
                notes.append(f"dark.exe did not yield an MSI ({brief}).")
                log.info("dark.exe: no MSI (%s)", brief[:120])

        if family == InstallerFamily.MSI:
            try:
                msi_meta = msi_lib.read_metadata(path)
            except Exception as exc:
                notes.append(f"MSI read failed: {exc}")
                log.warning("MSI read failed for %s: %s", path, exc)
        install_args, uninstall_args = silent_args_for(family)
        log_template = log_param_for(family)
        if family == InstallerFamily.MSI and msi_meta and msi_meta.product_code:
            uninstall_args = f"/x {msi_meta.product_code} /qn /norestart"
        if family != InstallerFamily.MSI and log_template is None and family != InstallerFamily.OTHER:
            notes.append(f"No standard log-file parameter for {family.value}.")
        log.info("Classified %s as %s", Path(path).name, family.value)
        updated.append(
            item.model_copy(
                update={
                    "path": path,
                    "extension": extension,
                    "family": family,
                    "msi": msi_meta,
                    "silent_install_args": install_args,
                    "silent_uninstall_args": uninstall_args,
                    "log_file_parameter": log_template,
                    "source_exe": source_exe,
                    "extracted_via_dark": extracted_via_dark,
                    "notes": notes,
                    "is_primary_candidate": family
                    not in {InstallerFamily.MST, InstallerFamily.OTHER},
                }
            )
        )
    return {"detected_installers": updated}
