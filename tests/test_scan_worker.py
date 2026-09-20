"""Small Qt worker boundary tests."""

from __future__ import annotations

from img_ai_filter.scan_worker import FunctionWorker


def test_worker_emits_progress_result_and_finished(qtbot) -> None:
    def operation(progress):
        progress(1, 3)
        progress(3, 3)
        return {"result": "complete"}

    worker = FunctionWorker(operation)
    progress = []
    results = []
    finished = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.succeeded.connect(results.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert progress == [(1, 3), (3, 3)]
    assert results == [{"result": "complete"}]
    assert finished == [True]


def test_worker_emits_exception_object_without_stringifying_private_data(qtbot) -> None:
    private = RuntimeError("private server body")
    worker = FunctionWorker(lambda progress: (_ for _ in ()).throw(private))
    failures = []
    results = []
    finished = []
    worker.failed.connect(failures.append)
    worker.succeeded.connect(results.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert failures == [private]
    assert results == []
    assert finished == [True]
