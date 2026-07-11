from __future__ import annotations

import json
import os
import re
from typing import Any

from packaging_ai.config import CONFIDENCE_THRESHOLD, PROJECT_ROOT
from packaging_ai.models import InstallPlan, ReviewReport
from packaging_ai.psadt.requirements import (
    exe_metadata_incomplete,
    is_valid_uninstall,
    load_psadt_requirements,
    requirements_findings,
)


def review_install_plan(plan: InstallPlan) -> ReviewReport:
    """LLM/Cursor review when configured; otherwise heuristic review (FR-11).

    Priority:
      1. CURSOR_API_KEY → Cursor SDK agent review
      2. OPENAI_API_KEY → OpenAI ChatOpenAI review
      3. heuristic review

    Always evaluates against Templates/PSADT_Requirements.md.
    Invalid uninstall forces confidence below the clarification threshold.
    """
    req_text = load_psadt_requirements()

    if os.environ.get("CURSOR_API_KEY"):
        try:
            return _finalize(_cursor_review(plan, req_text), plan)
        except Exception as exc:
            heuristic = _heuristic_review(plan)
            msg = str(exc)
            if "10038" in msg or "not a socket" in msg.lower():
                hint = (
                    "Cursor SDK bridge failed on Windows (WinError 10038). "
                    "Packaging continued with heuristic review. "
                    "Update to the latest Packaging AI code (Windows bridge patch) and retry."
                )
            else:
                hint = f"Cursor review failed ({exc}); used heuristic review."
            heuristic.findings.insert(0, hint)
            return _finalize(heuristic, plan)

    if os.environ.get("OPENAI_API_KEY"):
        try:
            return _finalize(_llm_review(plan, req_text), plan)
        except Exception as exc:
            heuristic = _heuristic_review(plan)
            heuristic.findings.insert(0, f"LLM review failed ({exc}); used heuristic review.")
            return _finalize(heuristic, plan)

    return _finalize(_heuristic_review(plan), plan)


def _finalize(report: ReviewReport, plan: InstallPlan) -> ReviewReport:
    findings = list(report.findings)
    score = float(report.confidence_score)

    if not is_valid_uninstall(plan.uninstall_command):
        msg = (
            "Requirements: a valid uninstall command is MANDATORY "
            "(clarification required)."
        )
        if msg not in findings:
            findings.append(msg)
        # Hard gate: always prompt for clarification
        score = min(score, CONFIDENCE_THRESHOLD - 0.01)

    if exe_metadata_incomplete(plan):
        msg = (
            "Requirements: EXE Publisher, AppName, and Version must be confirmed "
            "(clarification required)."
        )
        if msg not in findings:
            findings.append(msg)
        score = min(score, CONFIDENCE_THRESHOLD - 0.01)

    score = max(0.0, min(1.0, round(score, 2)))
    approved = (
        score >= CONFIDENCE_THRESHOLD
        and is_valid_uninstall(plan.uninstall_command)
        and not exe_metadata_incomplete(plan)
    )
    return report.model_copy(
        update={
            "confidence_score": score,
            "findings": findings,
            "approved": approved,
            "model": report.model or "heuristic",
            "reviewer": report.reviewer or "heuristic",
        }
    )


def _heuristic_review(plan: InstallPlan) -> ReviewReport:
    findings: list[str] = []
    score = 1.0

    req_findings = requirements_findings(plan)
    findings.extend(req_findings)
    score -= min(0.45, 0.1 * len(req_findings))

    if not is_valid_uninstall(plan.uninstall_command):
        score -= 0.35

    if not plan.primary_installer:
        score -= 0.5
    if not plan.app_name:
        score -= 0.15
    if not plan.app_version or (plan.app_version == "1.0.0" and not plan.product_code):
        findings.append("Version may be a placeholder.")
        score -= 0.1
    if not plan.app_vendor:
        findings.append("Vendor/manufacturer is empty.")
        score -= 0.1
    if not plan.install_command:
        score -= 0.25
    if plan.open_questions:
        findings.append(f"{len(plan.open_questions)} open question(s) remain.")
        score -= min(0.35, 0.1 * len(plan.open_questions))
    if plan.primary_family and plan.primary_family.value == "unknown_exe":
        findings.append("Unknown EXE family reduces confidence in silent switches.")
        score -= 0.2

    deduped: list[str] = []
    for item in findings:
        if item not in deduped:
            deduped.append(item)

    if not deduped:
        deduped.append("Plan looks complete for automated packaging (requirements checked).")

    score = max(0.0, min(1.0, round(score, 2)))
    return ReviewReport(
        confidence_score=score,
        findings=deduped,
        approved=score >= CONFIDENCE_THRESHOLD,
        model="heuristic",
        reviewer="heuristic",
    )


def _review_prompt(plan: InstallPlan, requirements_text: str) -> str:
    return (
        "You are a senior Windows software packaging expert reviewing an Install_Plan "
        "for a PSADT 3.10.2 package.\n"
        "Do NOT edit files, run tools, or change the repository. Review only.\n"
        "Enforce the PSADT script requirements below. A valid uninstall command is mandatory.\n"
        "Scoring rules:\n"
        "- If the plan fully meets the requirements with no issues, set confidence_score to 1.0.\n"
        "- Only lower confidence when you list concrete problems in findings.\n"
        "- Do not invent soft nits or withhold 1.0 without findings.\n"
        "- findings must be an array of issue strings; use [] when there are no issues.\n"
        "Respond with JSON only (no markdown fences, no prose):\n"
        '{"confidence_score": <float 0-1>, "findings": [<string>, ...]}\n\n'
        f"PSADT script requirements:\n{requirements_text}\n\n"
        f"Install_Plan JSON:\n{plan.model_dump_json(indent=2)}"
    )


def _report_from_review_text(
    content: str,
    plan: InstallPlan,
    *,
    model: str,
    reviewer: str,
) -> ReviewReport:
    parsed = _parse_json(content)
    score = float(parsed.get("confidence_score", 0.5))
    score = max(0.0, min(1.0, score))
    raw_findings = parsed.get("findings", [])
    if not isinstance(raw_findings, list):
        raw_findings = [raw_findings]
    findings = [str(f) for f in raw_findings if str(f).strip()]

    req_issues = requirements_findings(plan)
    for item in req_issues:
        if item not in findings:
            findings.append(item)

    # Empty findings + no requirements issues ⇒ treat as fully clean (1.0).
    # Models sometimes return 0.9x with [] for no reason.
    if not findings and not req_issues:
        score = 1.0
        findings = ["Plan looks complete for automated packaging (requirements checked)."]
    elif not findings:
        findings = ["No findings returned."]

    return ReviewReport(
        confidence_score=score,
        findings=findings,
        approved=score >= CONFIDENCE_THRESHOLD,
        model=model,
        reviewer=reviewer,
        raw_response=content,
    )


def _cursor_review(plan: InstallPlan, requirements_text: str) -> ReviewReport:
    """Review via Cursor SDK (CURSOR_API_KEY).

    Uses a no-repo cloud agent by default (avoids Windows local bridge /
    WinError 10038). Set PACKAGING_AI_CURSOR_RUNTIME=local to force local.
    Still runs in a subprocess for process isolation.
    """
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    from packaging_ai.config import DEFAULT_REVIEW_MODEL

    if not (os.environ.get("CURSOR_API_KEY") or "").strip():
        raise RuntimeError("CURSOR_API_KEY is not set.")

    prompt = _review_prompt(plan, requirements_text)
    with tempfile.TemporaryDirectory(prefix="pkgai_cursor_") as tmp:
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
            raise RuntimeError(f"Cursor review worker produced no result: {detail}")

        payload = json.loads(result_file.read_text(encoding="utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or "Cursor review failed."))

        content = str(payload.get("content") or "")
        if not content.strip():
            raise RuntimeError("Cursor review returned empty result text.")
        model = str(payload.get("model") or env.get("PACKAGING_AI_MODEL") or DEFAULT_REVIEW_MODEL)
        return _report_from_review_text(
            content, plan, model=model, reviewer="cursor"
        )


def _llm_review(plan: InstallPlan, requirements_text: str) -> ReviewReport:
    """Review via OpenAI (OPENAI_API_KEY) — optional fallback."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    from packaging_ai.config import DEFAULT_OPENAI_MODEL

    llm = ChatOpenAI(model=DEFAULT_OPENAI_MODEL, temperature=0)
    system = (
        "You are a senior Windows software packaging expert reviewing an Install_Plan "
        "for a PSADT 3.10.2 package. Enforce the PSADT script requirements provided by the user. "
        "A valid uninstall command is mandatory. "
        "Respond with JSON only: "
        '{"confidence_score": float 0-1, "findings": [string, ...]}'
    )
    human = (
        f"PSADT script requirements:\n{requirements_text}\n\n"
        f"Review this Install_Plan against those requirements:\n"
        f"{plan.model_dump_json(indent=2)}"
    )
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
    content = getattr(response, "content", str(response))
    return _report_from_review_text(
        content if isinstance(content, str) else str(content),
        plan,
        model=DEFAULT_OPENAI_MODEL,
        reviewer="openai",
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise
