"""Command-line validation for a local evaluation dataset."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from img_ai_filter.dataset import validate_dataset
from img_ai_filter.evaluation import ManifestError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", metavar="dataset-root", type=Path)
    parser.add_argument("manifest_path", metavar="manifest-path", type=Path)
    args = parser.parse_args(argv)

    try:
        result = validate_dataset(args.dataset_root, args.manifest_path)
    except (OSError, ManifestError) as error:
        print(f"cannot read manifest: {error}", file=sys.stderr)
        return 1

    if result.valid:
        print("dataset=valid exploratory=False errors=0")
        return 0

    for error in result.errors:
        print(error)
    print(f"dataset=invalid exploratory=True errors={len(result.errors)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
