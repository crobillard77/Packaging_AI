from __future__ import annotations

from pathlib import Path

from packaging_ai.graph.clarify_needs import clarification_needs
from packaging_ai.graph.state import PackagingState
from packaging_ai.logutil import get_logger
from packaging_ai.psadt.requirements import (
    exe_metadata_incomplete,
    is_valid_uninstall,
    normalize_uninstall_command,
    parse_meta_clarification,
)

log = get_logger("graph.clarify")


def clarify_node(state: PackagingState) -> dict:
    """Prompt the user when confidence < 0.75 (FR-12).

    EXE metadata (Publisher|AppName|Version) and uninstall must be confirmed;
    --yes cannot skip those prompts.

    When ``interactive`` is False (API jobs), pause with ``awaiting_clarification``
    instead of calling ``input()``.
    """
    needs = clarification_needs(state)
    needs_meta = bool(needs["needs_meta"])
    needs_uninstall = bool(needs["needs_uninstall"])
    needs_custom_clarify = bool(needs.get("needs_custom_clarify"))
    plan = state.get("install_plan")

    # --yes may skip soft clarification, but never EXE metadata, uninstall, or custom reqs
    if (
        state.get("auto_confirm")
        and not needs_meta
        and not needs_uninstall
        and not needs_custom_clarify
    ):
        log.info("Auto-confirming soft low-confidence review (--yes)")
        return {
            "user_clarifications": [
                "User auto-confirmed despite low confidence (--yes)."
            ],
            "user_confirmed": True,
            "awaiting_clarification": False,
        }

    findings = state.get("review_findings") or []
    score = state.get("confidence_score", 0.0)
    log.info(
        "Clarification required (confidence=%.2f, needs_meta=%s, needs_uninstall=%s, "
        "needs_custom_clarify=%s, interactive=%s)",
        score,
        needs_meta,
        needs_uninstall,
        needs_custom_clarify,
        state.get("interactive", True),
    )

    if state.get("interactive") is False:
        log.info("API mode: pausing for clarification via REST")
        return {
            "awaiting_clarification": True,
            "user_confirmed": False,
        }

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
        log.info("EXE metadata accepted: %s|%s|%s", vendor, name, version)
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
        log.info("Uninstall command accepted: %s", normalized)
        return {
            "user_clarifications": [f"UNINSTALL_CMD:{normalized}"],
            "user_confirmed": False,
        }

    if needs_custom_clarify:
        from packaging_ai.planning.custom_requirements import CUSTOM_REQ_PREFIX

        print(
            "\nCustom requirements need clarification.\n"
            "Answer the open questions below (paths, timing: pre/post/uninstall).\n"
            "Type 'abort' to cancel:"
        )
        try:
            answer = input("> ").strip()
        except EOFError:
            answer = "abort"
        if answer.lower() in {"abort", "quit", "exit", "n", "no"}:
            return {"error": "Aborted by user during clarification.", "user_clarifications": []}
        if not answer:
            return {
                "error": "Custom requirement answers are required.",
                "user_clarifications": [],
            }
        return {
            "user_clarifications": [f"{CUSTOM_REQ_PREFIX}{answer}"],
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
