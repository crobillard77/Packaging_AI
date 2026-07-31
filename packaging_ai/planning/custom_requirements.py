"""Apply operator custom requirements onto an InstallPlan via LLM."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from packaging_ai.config import PROJECT_ROOT
from packaging_ai.logutil import get_logger
from packaging_ai.models import InstallPlan

log = get_logger("planning.custom_requirements")

CUSTOM_REQ_PREFIX = "CUSTOM_REQ:"
APPLIED_CUSTOM_MARKER = "Applied operator custom requirements to plan step lists."


def custom_requirements_applied(plan: InstallPlan | None) -> bool:
    """True when a prior apply pass merged at least one custom step onto the plan."""
    if plan is None:
        return False
    return APPLIED_CUSTOM_MARKER in (plan.assumptions or [])


def apply_custom_requirements(
    plan: InstallPlan,
    custom_requirements: str,
    user_clarifications: list[str] | None = None,
) -> InstallPlan:
    """Merge free-text custom requirements into plan step lists.

    Uses Cursor → OpenAI → heuristic (open questions only; never invents steps).
    """
    text = (custom_requirements or "").strip()
    if not text:
        return plan

    clarifications = list(user_clarifications or [])
    custom_answers = [
        c[len(CUSTOM_REQ_PREFIX) :].strip()
        for c in clarifications
        if c.startswith(CUSTOM_REQ_PREFIX) and c[len(CUSTOM_REQ_PREFIX) :].strip()
    ]

    llm_errors: list[str] = []
    cursor_key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

    if cursor_key:
        try:
            log.info("Applying custom requirements via Cursor SDK...")
            parsed = _cursor_apply(plan, text, custom_answers)
            _ensure_llm_produced_work(parsed)
            return _merge(parsed, plan)
        except Exception as exc:
            log.warning("Cursor custom-requirements apply failed (%s); trying OpenAI/heuristic", exc)
            llm_errors.append(f"Cursor: {exc}")
    else:
        log.info("CURSOR_API_KEY not set in this process; skipping Cursor custom-requirements")

    if openai_key:
        try:
            log.info("Applying custom requirements via OpenAI...")
            parsed = _openai_apply(plan, text, custom_answers)
            _ensure_llm_produced_work(parsed)
            return _merge(parsed, plan)
        except Exception as exc:
            log.warning("OpenAI custom-requirements apply failed (%s); using heuristic", exc)
            llm_errors.append(f"OpenAI: {exc}")
    else:
        log.info("OPENAI_API_KEY not set in this process; skipping OpenAI custom-requirements")

    log.info("Heuristic custom-requirements path (no usable LLM)")
    return _merge(_heuristic_apply(plan, text, custom_answers, llm_errors), plan)


def _ensure_llm_produced_work(parsed: dict[str, Any]) -> None:
    """Reject empty LLM payloads so we do not silently drop operator requirements."""
    steps = (
        _str_list(parsed.get("pre_install_steps"))
        + _str_list(parsed.get("post_install_steps"))
        + _str_list(parsed.get("post_uninstall_steps"))
    )
    questions = _str_list(parsed.get("open_questions"))
    if not steps and not questions:
        raise RuntimeError(
            "LLM returned no plan steps and no open questions for custom requirements"
        )


def _heuristic_apply(
    plan: InstallPlan,
    text: str,
    custom_answers: list[str],
    llm_errors: list[str] | None = None,
) -> dict[str, Any]:
    """Do not invent PSADT steps; force clarification of unclear custom text."""
    questions = list(plan.open_questions)
    errors = [e.strip() for e in (llm_errors or []) if e and str(e).strip()]
    if custom_answers and errors:
        questions.append(
            "Custom requirements still could not be converted into plan steps "
            f"({'; '.join(errors)}). Answers received: {custom_answers[-1][:500]}"
        )
    elif custom_answers:
        questions.append(
            "Custom requirements still need a working Cursor or OpenAI key in the "
            "API process to convert answers into plan steps. "
            f"Answers received: {custom_answers[-1][:500]}"
        )
    elif errors:
        questions.append(
            "Custom requirements could not be interpreted automatically "
            f"({'; '.join(errors)}). "
            "Please restate each requirement clearly, including full paths and when "
            f"it should run (pre-install / post-install / uninstall). Original text:\n{text}"
        )
    else:
        questions.append(
            "Custom requirements could not be interpreted automatically "
            "(CURSOR_API_KEY / OPENAI_API_KEY not set on the API process). "
            "Set the key on the uvicorn/Windows service environment and restart, "
            "or restate each requirement clearly with full paths and when it should "
            f"run (pre-install / post-install / uninstall). Original text:\n{text}"
        )
    return {
        "pre_install_steps": [],
        "post_install_steps": [],
        "post_uninstall_steps": [],
        "open_questions": questions,
        "assumptions": [
            "Custom requirements pending LLM interpretation or operator clarification."
        ],
    }


def _apply_prompt(plan: InstallPlan, text: str, custom_answers: list[str]) -> str:
    answers_block = (
        "\n".join(f"- {a}" for a in custom_answers) if custom_answers else "(none yet)"
    )
    return (
        "You are a senior Windows PSADT 3.10.2 packaging expert.\n"
        "Do NOT edit files or run tools. Convert operator custom requirements into "
        "Install_Plan step lists only.\n"
        "Rules:\n"
        "- Map clear requirements to PowerShell/PSADT-friendly step strings "
        "that can run as-is inside Deploy-Application.ps1 (not comments, not prose).\n"
        "- pre_install_steps: run before install (e.g. domain membership checks with "
        "Exit-Script if not in domain)\n"
        "- post_install_steps: run after install (e.g. import .reg, Set-RegistryKey)\n"
        "- post_uninstall_steps: run after uninstall (e.g. Remove-Item folder)\n"
        "- Domain/gate conditions belong in pre_install_steps as explicit PowerShell, "
        "not as open_questions, when the domain name is already given.\n"
        "- Example domain gate: "
        "if (-not (Get-CimInstance Win32_ComputerSystem).Domain -match '(?i)^ABC(\\.|$)') "
        "{ Exit-Script -ExitCode 70001 }\n"
        "- If anything is ambiguous (missing path, unclear timing, incomplete .reg "
        "reference), put a concrete question in open_questions and do NOT invent "
        "that step.\n"
        "- Prefer explicit absolute or $envProgramFiles-style paths when given.\n"
        "- You MUST return at least one executable step OR one open_question.\n"
        "- Respond with JSON only (no markdown fences):\n"
        '{"pre_install_steps":[],"post_install_steps":[],"post_uninstall_steps":[],'
        '"open_questions":[],"assumptions":[]}\n\n'
        f"Operator custom requirements:\n{text}\n\n"
        f"Operator clarification answers (CUSTOM_REQ):\n{answers_block}\n\n"
        f"Current Install_Plan JSON:\n{plan.model_dump_json(indent=2)}"
    )


def _cursor_apply(plan: InstallPlan, text: str, custom_answers: list[str]) -> dict[str, Any]:
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    from packaging_ai.config import DEFAULT_REVIEW_MODEL

    prompt = _apply_prompt(plan, text, custom_answers)
    with tempfile.TemporaryDirectory(prefix="pkgai_custom_") as tmp:
        tmp_path = Path(tmp)
        prompt_file = tmp_path / "prompt.txt"
        result_file = tmp_path / "result.json"
        prompt_file.write_text(prompt, encoding="utf-8")

        env = os.environ.copy()
        env["PACKAGING_AI_ROOT"] = str(PROJECT_ROOT)
        env.setdefault("PACKAGING_AI_CURSOR_RUNTIME", "cloud")
        env.setdefault("PACKAGING_AI_MODEL", DEFAULT_REVIEW_MODEL)
        env.pop("CURSOR_USE_HTTP1", None)

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "packaging_ai.planning.cursor_review_worker",
                str(prompt_file),
                str(result_file),
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("PACKAGING_AI_CURSOR_TIMEOUT", "600")),
            check=False,
        )
        if not result_file.is_file():
            detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise RuntimeError(f"Cursor custom-requirements worker produced no result: {detail}")
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or "Cursor custom-requirements failed."))
        content = str(payload.get("content") or "")
        if not content.strip():
            raise RuntimeError("Cursor custom-requirements returned empty result text.")
        return _parse_apply_json(content)


def _openai_apply(plan: InstallPlan, text: str, custom_answers: list[str]) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from packaging_ai.config import DEFAULT_OPENAI_MODEL, DEFAULT_OPENAI_TEMPERATURE

    llm = ChatOpenAI(
        model=DEFAULT_OPENAI_MODEL,
        temperature=DEFAULT_OPENAI_TEMPERATURE,
    )
    system = (
        "You convert Windows packaging custom requirements into Install_Plan step JSON. "
        "Respond with JSON only: "
        '{"pre_install_steps":[],"post_install_steps":[],"post_uninstall_steps":[],'
        '"open_questions":[],"assumptions":[]}'
    )
    response = llm.invoke(
        [SystemMessage(content=system), HumanMessage(content=_apply_prompt(plan, text, custom_answers))]
    )
    content = getattr(response, "content", str(response))
    return _parse_apply_json(content if isinstance(content, str) else str(content))


def _parse_apply_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge(parsed: dict[str, Any], plan: InstallPlan) -> InstallPlan:
    pre = list(plan.pre_install_steps)
    post = list(plan.post_install_steps)
    post_un = list(plan.post_uninstall_steps)
    added = 0
    for item in _str_list(parsed.get("pre_install_steps")):
        if item not in pre:
            pre.append(item)
            added += 1
    for item in _str_list(parsed.get("post_install_steps")):
        if item not in post:
            post.append(item)
            added += 1
    for item in _str_list(parsed.get("post_uninstall_steps")):
        if item not in post_un:
            post_un.append(item)
            added += 1

    assumptions = list(plan.assumptions)
    for item in _str_list(parsed.get("assumptions")):
        if item not in assumptions and item != APPLIED_CUSTOM_MARKER:
            assumptions.append(item)
    if added:
        if APPLIED_CUSTOM_MARKER not in assumptions:
            assumptions.append(APPLIED_CUSTOM_MARKER)

    # Replace prior custom open questions with latest from this apply pass,
    # keep non-custom open questions from rule-based plan.
    prior_custom_marker = "Custom requirements"
    kept_questions = [
        q for q in plan.open_questions if prior_custom_marker not in q and "CUSTOM_REQ" not in q
    ]
    for item in _str_list(parsed.get("open_questions")):
        if item not in kept_questions:
            kept_questions.append(item)

    return plan.model_copy(
        update={
            "pre_install_steps": pre,
            "post_install_steps": post,
            "post_uninstall_steps": post_un,
            "assumptions": assumptions,
            "open_questions": kept_questions,
        }
    )
