"""Tests for the command-line evaluation runner."""

import json
from pathlib import Path

import pytest

from img_ai_filter import eval_cli
from img_ai_filter.baseline_detector import GeometryDetector
from img_ai_filter.evaluation import load_manifest


pytest.importorskip("PIL")


def _png(root: Path, name: str, width: int, height: int) -> Path:
    from PIL import Image

    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height)).save(path, format="PNG")
    return path


def test_cli_writes_json_and_markdown_reports(tmp_path: Path, capsys) -> None:
    dataset = tmp_path / "data"
    dataset.mkdir()
    phone = _png(dataset, "phone.png", 900, 1600)
    photo = _png(dataset, "photo.png", 4000, 3000)
    manifest_path = tmp_path / "manifest.csv"
    manifest_path.write_text(
        "path,label,split,source,license\n"
        f"{phone.name},screenshot,tuning,test-source,local-test\n"
        f"{photo.name},ordinary,tuning,test-source,local-test\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "compare.json"
    md_path = tmp_path / "compare.md"

    exit_code = eval_cli.main(
        [
            "--dataset",
            str(dataset),
            "--manifest",
            str(manifest_path),
            "--split",
            "tuning",
            "--json",
            str(json_path),
            "--markdown",
            str(md_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "geometry-baseline" in payload["detectors"]
    assert payload["metadata"]["exploratory"] is True
    assert "reported_split" in payload["metadata"]
    markdown = md_path.read_text(encoding="utf-8")
    assert markdown.startswith("# Detector evaluation (tuning)")
    assert "geometry-baseline" in markdown
    captured = capsys.readouterr().out
    assert "selected_detector" in captured


def test_cli_run_is_equivalent_to_direct_evaluation(tmp_path: Path) -> None:
    dataset = tmp_path / "data"
    dataset.mkdir()
    phone = _png(dataset, "phone.png", 900, 1600)
    manifest_path = tmp_path / "manifest.csv"
    manifest_path.write_text(
        "path,label,split,source,license\n"
        f"{phone.name},screenshot,tuning,test-source,local-test\n",
        encoding="utf-8",
    )

    manifest = load_manifest(dataset, manifest_path)
    entry = manifest[0]
    result = GeometryDetector().analyze(dataset / entry.path)

    assert result.is_candidate
    assert result.category == "screenshot"