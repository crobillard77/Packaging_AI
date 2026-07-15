"""Run: python -m packaging_ai.api"""

from __future__ import annotations

import uvicorn

from packaging_ai.config import API_HOST, API_PORT


def main() -> None:
    uvicorn.run(
        "packaging_ai.api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
