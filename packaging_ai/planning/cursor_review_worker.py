"""Isolated Cursor SDK review worker (run in a subprocess).

Default runtime is a no-repo cloud agent so Windows does not need the local
SDK socket bridge (which commonly fails with WinError 10038).

Set PACKAGING_AI_CURSOR_RUNTIME=local to force a local agent instead.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: cursor_review_worker <prompt_path> <result_path>", file=sys.stderr)
        return 2

    prompt_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    prompt = prompt_path.read_text(encoding="utf-8")
    api_key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if not api_key:
        result_path.write_text(
            json.dumps({"ok": False, "error": "CURSOR_API_KEY is not set"}),
            encoding="utf-8",
        )
        return 1

    model = os.environ.get("PACKAGING_AI_MODEL")
    if not model:
        try:
            from packaging_ai.config import DEFAULT_REVIEW_MODEL

            model = DEFAULT_REVIEW_MODEL
        except Exception:
            model = "composer-2.5"
    model = str(model).strip() or "composer-2.5"
    cwd = os.environ.get("PACKAGING_AI_ROOT") or str(Path(__file__).resolve().parents[2])
    runtime = (os.environ.get("PACKAGING_AI_CURSOR_RUNTIME") or "cloud").strip().lower()

    try:
        # Must patch before any cursor_sdk bridge launch (cloud + local).
        from packaging_ai.planning.cursor_windows_patch import apply_windows_bridge_patch

        apply_windows_bridge_patch()

        from cursor_sdk import (
            Agent,
            AgentOptions,
            CloudAgentOptions,
            CursorAgentError,
            LocalAgentOptions,
        )
    except ImportError as exc:
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"cursor_sdk is not installed in this Python "
                        f"({sys.executable}): {exc}. "
                        'Install with: pip install -e ".[cursor]" '
                        "(use the same interpreter as the Windows service)."
                    ),
                    "runtime": runtime,
                    "python": sys.executable,
                }
            ),
            encoding="utf-8",
        )
        return 1

    try:
        if runtime == "local":
            options = AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd),
            )
        else:
            # No-repo cloud agent: empty workspace; review payload is in the prompt.
            options = AgentOptions(
                api_key=api_key,
                model=model,
                cloud=CloudAgentOptions(),
            )

        result = Agent.prompt(prompt, options)
    except CursorAgentError as exc:
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Cursor agent failed to start: {exc}",
                    "retryable": getattr(exc, "is_retryable", None),
                    "runtime": runtime,
                }
            ),
            encoding="utf-8",
        )
        return 1
    except OSError as exc:
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"Cursor OS error ({exc}). "
                        "On Windows local agents often hit WinError 10038; "
                        "use cloud runtime (default) instead of PACKAGING_AI_CURSOR_RUNTIME=local."
                    ),
                    "runtime": runtime,
                }
            ),
            encoding="utf-8",
        )
        return 1
    except Exception as exc:  # noqa: BLE001 — surface any worker failure to parent
        result_path.write_text(
            json.dumps({"ok": False, "error": str(exc), "runtime": runtime}),
            encoding="utf-8",
        )
        return 1

    if getattr(result, "status", None) == "error":
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Cursor review run failed (id={getattr(result, 'id', '?')})",
                    "runtime": runtime,
                }
            ),
            encoding="utf-8",
        )
        return 1

    content = getattr(result, "result", None) or ""
    if not str(content).strip():
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": "Cursor review returned empty result text.",
                    "runtime": runtime,
                }
            ),
            encoding="utf-8",
        )
        return 1

    result_path.write_text(
        json.dumps(
            {
                "ok": True,
                "content": str(content),
                "runtime": runtime,
                "model": model,
            }
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
