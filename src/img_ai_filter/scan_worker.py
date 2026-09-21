"""Small Qt worker for running one callable outside the GUI thread."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class OperationThread(QThread):
    """Run one operation with no cross-thread worker-object lifetime."""

    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, operation: Callable[[Callable[[int, int], None]], Any], parent=None) -> None:
        super().__init__(parent)
        self._operation = operation
        self.result: Any = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            result = self._operation(self.progress.emit)
        except Exception as error:
            self.error = error
            self.failed.emit(error)
        else:
            self.result = result
            self.succeeded.emit(result)
