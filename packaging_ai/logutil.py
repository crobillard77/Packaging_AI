from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False
LOGGER_NAME = "packaging_ai"
_FILE_FORMATTER = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_RUN_BUFFER: "_BufferHandler | None" = None
_PACKAGE_HANDLER: logging.FileHandler | None = None


class _BufferHandler(logging.Handler):
    """Capture formatted log lines for the current packaging run."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []
        self.setFormatter(_FILE_FORMATTER)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            self.handleError(record)


def setup_logging(
    level: str | int = "INFO",
    *,
    log_file: str | Path | None = None,
    console: bool = True,
) -> logging.Logger:
    """Configure the packaging_ai logger (idempotent).

    Console: human-readable INFO+ by default.
    Optional file: full detail including DEBUG when level is DEBUG.
    """
    global _CONFIGURED
    root = logging.getLogger(LOGGER_NAME)
    numeric = _resolve_level(level)

    if _CONFIGURED:
        root.setLevel(numeric)
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setLevel(numeric)
        return root

    root.setLevel(numeric)
    root.propagate = False
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(numeric)
        stream.setFormatter(console_formatter)
        root.addHandler(stream)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(_FILE_FORMATTER)
        root.addHandler(file_handler)

    _CONFIGURED = True
    root.debug(
        "Logging configured (level=%s, file=%s)",
        logging.getLevelName(numeric),
        log_file,
    )
    return root


def begin_run_capture() -> None:
    """Start buffering log lines for the current packaging run."""
    global _RUN_BUFFER, _PACKAGE_HANDLER
    root = logging.getLogger(LOGGER_NAME)
    end_package_log()
    if _RUN_BUFFER is not None:
        root.removeHandler(_RUN_BUFFER)
    _RUN_BUFFER = _BufferHandler()
    root.addHandler(_RUN_BUFFER)
    root.debug("Started per-run log capture for package logs/")


def write_package_log(logs_dir: str | Path, filename: str = "Packaging_AI.log") -> Path:
    """Write buffered run logs into {logs_dir}/{filename} and keep appending there."""
    global _RUN_BUFFER, _PACKAGE_HANDLER
    root = logging.getLogger(LOGGER_NAME)
    logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)
    log_path = logs_path / filename

    lines = list(_RUN_BUFFER.lines) if _RUN_BUFFER is not None else []
    log_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    end_package_log()
    if _RUN_BUFFER is not None:
        root.removeHandler(_RUN_BUFFER)
        _RUN_BUFFER = None

    _PACKAGE_HANDLER = logging.FileHandler(log_path, encoding="utf-8")
    _PACKAGE_HANDLER.setLevel(logging.DEBUG)
    _PACKAGE_HANDLER.setFormatter(_FILE_FORMATTER)
    root.addHandler(_PACKAGE_HANDLER)
    root.info("Package run log: %s", log_path)
    return log_path


def end_package_log() -> None:
    """Detach the per-package file handler (if any)."""
    global _PACKAGE_HANDLER
    if _PACKAGE_HANDLER is None:
        return
    root = logging.getLogger(LOGGER_NAME)
    root.removeHandler(_PACKAGE_HANDLER)
    _PACKAGE_HANDLER.close()
    _PACKAGE_HANDLER = None


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under packaging_ai."""
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def _resolve_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    text = str(level or "INFO").strip().upper()
    return getattr(logging, text, logging.INFO)
