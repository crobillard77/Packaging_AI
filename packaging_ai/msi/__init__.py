"""Thin MSI library contract (v1 read-only; edit/create later)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from packaging_ai.models import MsiMetadata


@runtime_checkable
class MsiLibrary(Protocol):
    """Interface for MSI operations.

    v1 implements read-only query. Edit/create will be provided by a
    dedicated library in a later phase without redesigning the graph.
    """

    def read_metadata(self, msi_path: str) -> MsiMetadata:
        """Open an MSI read-only and return product metadata."""
        ...

    # --- Future (Phase 2) — not implemented in v1 ---
    # def edit_msi(self, msi_path: str, changes: dict) -> None: ...
    # def create_msi(self, spec: dict, output_path: str) -> None: ...


class MsiEditNotSupportedError(NotImplementedError):
    """Raised when edit/create is requested before the Phase 2 library exists."""
