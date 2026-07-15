from __future__ import annotations

import hashlib
from pathlib import Path

from packaging_ai.models import FileHashInfo


def sha256_file(path: str | Path) -> FileHashInfo:
    file_path = Path(path)
    digest = hashlib.sha256()
    size = 0
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return FileHashInfo(path=str(file_path.resolve()), sha256=digest.hexdigest(), size_bytes=size)
