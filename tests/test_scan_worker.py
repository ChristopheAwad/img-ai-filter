"""Tests for the generic background operation thread."""

from __future__ import annotations

from img_ai_filter.scan_worker import OperationThread


def test_operation_thread_retains_success_result(qtbot) -> None:
    result = object()
    thread = OperationThread(lambda progress: result)

    with qtbot.waitSignal(thread.finished):
        thread.start()

    assert thread.result is result
    assert thread.error is None


def test_operation_thread_retains_error(qtbot) -> None:
    error = RuntimeError("private worker failure")

    def fail(progress):
        raise error

    thread = OperationThread(fail)
    with qtbot.waitSignal(thread.finished):
        thread.start()

    assert thread.result is None
    assert thread.error is error
