from __future__ import annotations

from packaging_ai.models import InstallerFamily

# Silent install / uninstall switches by installer family (FR-4)
_SILENT: dict[InstallerFamily, tuple[str, str | None]] = {
    InstallerFamily.MSI: (
        "/qn /norestart",
        "/x {PRODUCT_CODE} /qn /norestart",
    ),
    InstallerFamily.INNO_SETUP: (
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-",
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART",
    ),
    InstallerFamily.NSIS: ("/S", "/S"),
    InstallerFamily.INSTALLSHIELD: ('/s /v"/qn"', '/s /v"/qn"'),
    InstallerFamily.WIX_BURN: ("/quiet /norestart", "/uninstall /quiet /norestart"),
    InstallerFamily.ADVANCED_INSTALLER: ("/qn", "/qn"),
    InstallerFamily.SQUIRREL: ("--silent", "--uninstall --silent"),
    InstallerFamily.INSTALL4J: ("-q", "-q"),
    InstallerFamily.UNKNOWN_EXE: ("", None),
}

# Log-file CLI parameter templates. Use {LOG} as the log path placeholder.
# None = family has no standard log switch (do not invent one).
_LOG_PARAM: dict[InstallerFamily, str | None] = {
    InstallerFamily.MSI: '/l*v "{LOG}"',
    InstallerFamily.INNO_SETUP: '/LOG="{LOG}"',
    # Standard NSIS (e.g. Notepad++) has no built-in log file switch
    InstallerFamily.NSIS: None,
    InstallerFamily.INSTALLSHIELD: '/f2"{LOG}"',
    InstallerFamily.WIX_BURN: '/log "{LOG}"',
    InstallerFamily.ADVANCED_INSTALLER: '/log "{LOG}"',
    InstallerFamily.SQUIRREL: None,
    InstallerFamily.INSTALL4J: "-Dinstall4j.keepLog=true -Dinstall4j.alternativeLogfile={LOG}",
    InstallerFamily.UNKNOWN_EXE: None,
}


def silent_args_for(family: InstallerFamily) -> tuple[str | None, str | None]:
    install, uninstall = _SILENT.get(family, ("", None))
    return (install or None, uninstall)


def log_param_for(family: InstallerFamily) -> str | None:
    """Return the family's log-file parameter template, or None if unsupported."""
    return _LOG_PARAM.get(family)


def build_install_parameters(
    family: InstallerFamily,
    *,
    log_path: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Return (install_params, uninstall_params, log_param_used).

    When the family supports logging and log_path is set, append the log switch.
    """
    install, uninstall = silent_args_for(family)
    install = install or ""
    template = log_param_for(family)
    log_used: str | None = None
    if template and log_path:
        log_used = template.replace("{LOG}", log_path)
        install = f"{install} {log_used}".strip()
    return install or None, uninstall, log_used
