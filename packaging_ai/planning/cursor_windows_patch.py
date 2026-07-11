"""Windows-safe Cursor SDK bridge discovery patch.

cursor-sdk's `_read_discovery` uses `selectors` on a stderr *pipe*. On Windows,
`select()` only accepts sockets, so bridge launch fails with WinError 10038
for both local and cloud agents (both use the local bridge process).

This module replaces `_read_discovery` with a threaded blocking reader on win32.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Mapping


def apply_windows_bridge_patch() -> None:
    if sys.platform != "win32":
        return

    import cursor_sdk._bridge as bridge
    from cursor_sdk.errors import CursorSDKError

    if getattr(bridge, "_pkgai_windows_discovery_patched", False):
        return

    def _read_discovery_windows(
        process: Any, timeout: float
    ) -> Mapping[str, Any]:
        if process.stderr is None:
            raise CursorSDKError("Bridge process stderr is unavailable")

        box: dict[str, Any] = {}

        def reader() -> None:
            try:
                stderr_lines: list[str] = []
                for line in process.stderr:
                    stderr_lines.append(line)
                    discovery = bridge.parse_discovery_line(line)
                    if discovery is not None:
                        box["discovery"] = discovery
                        return
                exit_code = process.poll()
                raise CursorSDKError(
                    f"Bridge exited before discovery with status {exit_code}: "
                    + "".join(stderr_lines)
                )
            except Exception as exc:  # noqa: BLE001 — capture for parent thread
                box["error"] = exc

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout)
        if "discovery" in box:
            return box["discovery"]
        if thread.is_alive():
            # Best-effort stop; Bridge.launch will terminate the process on error.
            raise CursorSDKError("Timed out waiting for bridge discovery")
        err = box.get("error")
        if isinstance(err, BaseException):
            raise err
        raise CursorSDKError("Timed out waiting for bridge discovery")

    bridge._read_discovery = _read_discovery_windows  # type: ignore[assignment]
    bridge._pkgai_windows_discovery_patched = True


def smoke_test_bridge(timeout: float = 30.0) -> str:
    """Launch/close the bridge once to verify discovery works. Returns ready URL."""
    apply_windows_bridge_patch()
    from cursor_sdk._bridge import Bridge

    bridge = Bridge.launch(workspace=".", timeout=timeout)
    try:
        return bridge.endpoint.url
    finally:
        bridge.close()
