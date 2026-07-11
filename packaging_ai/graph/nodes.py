from __future__ import annotations

from pathlib import Path

from packaging_ai.config import PRIMARY_INSTALLER_EXTENSIONS
from packaging_ai.installers import classify_by_extension, log_param_for, scan_folder, silent_args_for
from packaging_ai.models import DetectedInstaller, InstallerFamily
from packaging_ai.msi.reader import get_msi_library
from packaging_ai.planning import build_install_plan, review_install_plan
from packaging_ai.psadt import generate_psadt_package
from packaging_ai.psadt.requirements import (
    exe_metadata_incomplete,
    is_valid_uninstall,
    normalize_uninstall_command,
    parse_meta_clarification,
)
from packaging_ai.graph.state import PackagingState


def scan_node(state: PackagingState) -> dict:
    folder = state["folder_path"]
    paths = scan_folder(folder)
    detected = [
        DetectedInstaller(
            path=p,
            extension=Path(p).suffix.lower(),
            is_primary_candidate=Path(p).suffix.lower() in PRIMARY_INSTALLER_EXTENSIONS,
        )
        for p in paths
    ]
    return {"detected_installers": detected, "error": None}


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
            print(f"Trying dark.exe on {Path(path).name}...")
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
                    print(f"  dark.exe found MSI: {Path(main_msi).name}")
            else:
                brief = dark.message.splitlines()[0] if dark.message else "no MSI"
                notes.append(f"dark.exe did not yield an MSI ({brief}).")
                print(f"  dark.exe: no MSI ({brief[:120]})")

        if family == InstallerFamily.MSI:
            try:
                msi_meta = msi_lib.read_metadata(path)
            except Exception as exc:
                notes.append(f"MSI read failed: {exc}")
        install_args, uninstall_args = silent_args_for(family)
        log_template = log_param_for(family)
        if family == InstallerFamily.MSI and msi_meta and msi_meta.product_code:
            uninstall_args = f'/x {msi_meta.product_code} /qn /norestart'
        if family != InstallerFamily.MSI and log_template is None and family != InstallerFamily.OTHER:
            notes.append(f"No standard log-file parameter for {family.value}.")
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


def plan_node(state: PackagingState) -> dict:
    plan = build_install_plan(
        state.get("detected_installers") or [],
        state.get("user_clarifications") or [],
    )
    return {"install_plan": plan}


def review_node(state: PackagingState) -> dict:
    plan = state.get("install_plan")
    if plan is None:
        return {
            "confidence_score": 0.0,
            "review_findings": ["No install plan to review."],
            "review_report": None,
        }
    report = review_install_plan(plan)
    plan = plan.model_copy(
        update={
            "model": report.model,
            "reviewer": report.reviewer,
        }
    )
    return {
        "install_plan": plan,
        "confidence_score": report.confidence_score,
        "review_findings": report.findings,
        "review_report": report,
    }


def clarify_node(state: PackagingState) -> dict:
    """Prompt the user when confidence < 0.75 (FR-12).

    EXE metadata (Publisher|AppName|Version) and uninstall must be confirmed;
    --yes cannot skip those prompts.
    """
    plan = state.get("install_plan")
    clarifications = state.get("user_clarifications") or []
    already_got_meta = any(parse_meta_clarification(c) for c in clarifications)
    already_got_uninstall = any(c.startswith("UNINSTALL_CMD:") for c in clarifications)
    needs_meta = (
        plan is not None
        and not already_got_meta
        and exe_metadata_incomplete(plan)
    )
    needs_uninstall = (
        plan is not None
        and not already_got_uninstall
        and (
            not is_valid_uninstall(plan.uninstall_command)
            # Always confirm EXE uninstall so the user can paste/convert a path
            or (
                plan.primary_family is not None
                and plan.primary_family.value
                not in {"msi", "mst"}
            )
        )
    )

    # --yes may skip soft clarification, but never EXE metadata or uninstall prompts
    if state.get("auto_confirm") and not needs_meta and not needs_uninstall:
        return {
            "user_clarifications": [
                "User auto-confirmed despite low confidence (--yes)."
            ],
            "user_confirmed": True,
        }

    findings = state.get("review_findings") or []
    score = state.get("confidence_score", 0.0)
    print("\n=== Packaging AI — clarification required ===")
    print(f"Confidence score: {score:.2f} (threshold 0.75)")
    print("Findings:")
    for f in findings:
        print(f"  - {f}")
    if plan and plan.open_questions:
        print("Open questions:")
        for q in plan.open_questions:
            print(f"  - {q}")

    if needs_meta and plan is not None:
        guessed_name = plan.app_name or (
            Path(plan.primary_installer).stem if plan.primary_installer else "AppName"
        )
        print(
            "\nEXE Publisher, AppName, and Version could not be read from the installer.\n"
            "Enter them at the '>' prompt as: Publisher|AppName|Version\n"
            f"  Example: Notepad++|{guessed_name}|8.9.6.2\n"
            "Type 'abort' to cancel:"
        )
        try:
            answer = input("> ").strip()
        except EOFError:
            answer = "abort"
        if answer.lower() in {"abort", "quit", "exit", "n", "no"}:
            return {"error": "Aborted by user during clarification.", "user_clarifications": []}
        # Allow with or without META: prefix
        raw = answer[5:].strip() if answer.upper().startswith("META:") else answer
        meta = parse_meta_clarification(f"META:{raw}")
        if meta is None:
            print(
                "Invalid format. Enter exactly: Publisher|AppName|Version\n"
                f"  Example: Notepad++|{guessed_name}|8.9.6.2"
            )
            return {
                "error": "Invalid EXE metadata; packaging stopped.",
                "user_clarifications": [],
            }
        vendor, name, version = meta
        print(f"Using metadata: Publisher={vendor}, AppName={name}, Version={version}")
        return {
            "user_clarifications": [f"META:{vendor}|{name}|{version}"],
            "user_confirmed": False,
        }

    if needs_uninstall:
        print(
            "\nConfirm uninstall (required for EXE / when missing).\n"
            "Enter it at the '>' prompt below (Python input — not a PowerShell command).\n"
            "Paste a path like this and it will be converted to Execute-Process:\n"
            '  "C:\\Program Files\\Notepad++\\uninstall.exe" /S\n'
        )
        if plan and plan.suggested_uninstall:
            print(f"Suggested (after conversion):\n  {plan.suggested_uninstall}")
            print("Type 'suggest' to accept the suggestion, or paste your own command.")
        print("Type 'abort' to cancel:")
        try:
            answer = input("> ").strip()
        except EOFError:
            answer = "abort"
        if answer.lower() in {"abort", "quit", "exit", "n", "no"}:
            return {"error": "Aborted by user during clarification.", "user_clarifications": []}
        if answer.lower() in {"suggest", "s"} and plan and plan.suggested_uninstall:
            normalized = plan.suggested_uninstall
        else:
            if "|" in answer and "Execute-" not in answer:
                path_part, args_part = answer.split("|", 1)
                answer = f'"{path_part.strip()}" {args_part.strip()}'
            normalized = normalize_uninstall_command(answer)
        if not is_valid_uninstall(normalized):
            print(
                "That does not look like a valid uninstall command.\n"
                'Paste exactly: "C:\\Program Files\\Notepad++\\uninstall.exe" /S'
            )
            return {
                "error": "Invalid uninstall command provided; packaging stopped.",
                "user_clarifications": [],
            }
        print(f"Converted uninstall:\n  {normalized}")
        return {
            "user_clarifications": [f"UNINSTALL_CMD:{normalized}"],
            "user_confirmed": False,
        }

    print(
        "\nEnter clarification (or 'confirm' to proceed with the current plan, "
        "'abort' to cancel):"
    )
    try:
        answer = input("> ").strip()
    except EOFError:
        answer = "abort"

    if answer.lower() in {"abort", "quit", "exit", "n", "no"}:
        return {"error": "Aborted by user during clarification.", "user_clarifications": []}
    if answer.lower() in {"confirm", "y", "yes", "ok"}:
        if plan is not None and not is_valid_uninstall(plan.uninstall_command):
            return {
                "error": "Cannot confirm: a valid uninstall command is mandatory.",
                "user_clarifications": [],
            }
        if plan is not None and exe_metadata_incomplete(plan):
            return {
                "error": "Cannot confirm: EXE Publisher, AppName, and Version are required.",
                "user_clarifications": [],
            }
        return {
            "user_clarifications": ["User confirmed current plan despite low confidence."],
            "user_confirmed": True,
        }
    return {"user_clarifications": [answer], "user_confirmed": False}


def generate_node(state: PackagingState) -> dict:
    if state.get("error"):
        return {}
    plan = state.get("install_plan")
    review = state.get("review_report")
    if plan is None:
        return {"error": "Cannot generate package without an Install_Plan."}
    if exe_metadata_incomplete(plan):
        return {
            "error": "Cannot generate package without EXE Publisher, AppName, and Version."
        }
    if not is_valid_uninstall(plan.uninstall_command):
        return {
            "error": "Cannot generate package without a valid uninstall command."
        }
    if review is None:
        from packaging_ai.models import ReviewReport

        review = ReviewReport(
            confidence_score=state.get("confidence_score", 0.0),
            findings=state.get("review_findings") or [],
            approved=True,
            model="unknown",
            reviewer="unknown",
        )
    output_dir = state.get("output_dir") or str(
        Path(__file__).resolve().parents[2] / "output"
    )
    artifacts = generate_psadt_package(plan, review, output_dir)
    return {"generated_artifacts": artifacts}


def route_after_review(state: PackagingState) -> str:
    if state.get("error"):
        return "end"
    plan = state.get("install_plan")
    clarifications = state.get("user_clarifications") or []
    already_got_meta = any(parse_meta_clarification(c) for c in clarifications)
    already_got_uninstall = any(c.startswith("UNINSTALL_CMD:") for c in clarifications)
    if plan is not None and exe_metadata_incomplete(plan) and not already_got_meta:
        return "clarify"
    if plan is not None and not is_valid_uninstall(plan.uninstall_command):
        return "clarify"
    if (
        plan is not None
        and plan.primary_family is not None
        and plan.primary_family.value not in {"msi", "mst"}
        and not already_got_uninstall
    ):
        return "clarify"
    if state.get("user_confirmed"):
        return "generate"
    if state.get("auto_confirm") and (
        plan is None
        or (
            is_valid_uninstall(plan.uninstall_command)
            and not exe_metadata_incomplete(plan)
        )
    ):
        return "generate"
    score = float(state.get("confidence_score") or 0.0)
    if score >= 0.75:
        return "generate"
    return "clarify"


def route_after_clarify(state: PackagingState) -> str:
    if state.get("error"):
        return "end"
    if state.get("user_confirmed"):
        return "generate"
    return "plan"
