"""Command-line runner for the offline detector evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys

from img_ai_filter.baseline_detector import GeometryDetector
from img_ai_filter.evaluation import (
    AcceptanceTargets,
    evaluate_detector,
    load_manifest,
    render_json,
    render_markdown,
)


def _metadata(manifest, split: str) -> dict[str, object]:
    counts: dict[str, int] = {}
    split_counts: dict[str, int] = {}
    for entry in manifest:
        counts[entry.label] = counts.get(entry.label, 0) + 1
        split_counts[entry.split] = split_counts.get(entry.split, 0) + 1
    return {
        "dataset_root": str(manifest.root),
        "label_counts": counts,
        "split_counts": split_counts,
        "reported_split": split,
        "platform": sys.platform,
        "python": platform.python_version(),
        "exploratory": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path, help="dataset root folder")
    parser.add_argument("--manifest", required=True, type=Path, help="CSV manifest")
    parser.add_argument("--split", choices=("tuning", "holdout"), default="holdout")
    parser.add_argument("--json", type=Path, help="output JSON report path")
    parser.add_argument("--markdown", type=Path, help="output Markdown report path")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.dataset, args.manifest)

    targets = AcceptanceTargets()
    detectors = {
        GeometryDetector.name: GeometryDetector(),
    }

    evaluations = {
        name: evaluate_detector(detector, manifest, args.split, targets=targets)
        for name, detector in detectors.items()
    }

    metadata = _metadata(manifest, args.split)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            render_json(evaluations, targets, args.split, metadata),
            encoding="utf-8",
        )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(
            render_markdown(evaluations, targets, args.split, metadata),
            encoding="utf-8",
        )

    choose = json.loads(render_json(evaluations, targets, args.split, metadata))[
        "selected_detector"
    ]
    print(f"split={args.split} selected_detector={choose}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())