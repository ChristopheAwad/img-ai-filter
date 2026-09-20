"""Small Qt worker for running one callable outside the GUI thread."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot


class FunctionWorker(QObject):
    """Run an operation and report its result without changing exceptions."""

    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, operation: Callable[[Callable[[int, int], None]], Any]) -> None:
        super().__init__()
        self._operation = operation

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation(self.progress.emit)
        except Exception as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()


class OperationThread(QThread):
    """Run one operation with no cross-thread worker-object lifetime."""

    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, operation: Callable[[Callable[[int, int], None]], Any], parent=None) -> None:
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            result = self._operation(self.progress.emit)
        except Exception as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)
