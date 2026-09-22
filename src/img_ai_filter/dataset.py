"""Validate the completeness and image content of a local evaluation dataset."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
from itertools import combinations
from pathlib import Path
import statistics
import warnings

from PIL import Image

from img_ai_filter.evaluation import load_manifest


MINIMUM_LABELS: dict[str, dict[str, int]] = {
    "ordinary": {"tuning": 105, "holdout": 45},
    "screenshot": {"tuning": 21, "holdout": 9},
    "captioned_meme": {"tuning": 18, "holdout": 7},
    "reaction_image": {"tuning": 18, "holdout": 7},
    "comic": {"tuning": 18, "holdout": 7},
    "image_macro": {"tuning": 18, "holdout": 7},
    "uncertain": {"tuning": 21, "holdout": 9},
}
TUNING_SHARE_MIN = 0.65
TUNING_SHARE_MAX = 0.75
SAFE_MAX_PIXELS = 100_000_000
CROSS_SPLIT_SIMILARITY_MIN = 0.985
CROSS_SPLIT_MEAN_DIFF_MAX = 16.0
_FEATURE_SIZE = (16, 16)
_FORMAT_BY_SUFFIX = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}


@dataclass(frozen=True, slots=True)
class DatasetValidation:
    valid: bool
    exploratory: bool
    errors: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _feature(path: Path) -> list[float] | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(path) as image:
                width, height = image.size
                if width * height > SAFE_MAX_PIXELS:
                    return None
                resized = image.convert("L").resize(_FEATURE_SIZE, Image.Resampling.LANCZOS)
                return [float(value) for value in resized.getdata()]
    except Exception:  # Decode failures are reported by the ordered decode check.
        return None


def _features_match(left: list[float], right: list[float]) -> bool:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_flat = statistics.pstdev(left) == 0
    right_flat = statistics.pstdev(right) == 0
    if left_flat and right_flat:
        return abs(left_mean - right_mean) <= 1.0
    if left_flat or right_flat:
        return False
    return (
        statistics.correlation(left, right) >= CROSS_SPLIT_SIMILARITY_MIN
        and abs(left_mean - right_mean) <= CROSS_SPLIT_MEAN_DIFF_MAX
    )


def validate_dataset(root: Path, manifest_path: Path) -> DatasetValidation:
    """Validate one manifest and its image files without modifying either."""
    manifest = load_manifest(root, manifest_path)
    counts = Counter((entry.label, entry.split) for entry in manifest)
    errors: list[str] = []

    minimum_errors: list[str] = []
    for label, required in MINIMUM_LABELS.items():
        for split in ("tuning", "holdout"):
            count = counts[label, split]
            minimum = required[split]
            if count < minimum:
                minimum_errors.append(
                    f"below minimum for {label} {split}: {count} of {minimum} required"
                )
    errors.extend(sorted(minimum_errors))

    share_errors: list[str] = []
    for label in MINIMUM_LABELS:
        tuning = counts[label, "tuning"]
        holdout = counts[label, "holdout"]
        total = tuning + holdout
        required_total = sum(MINIMUM_LABELS[label].values())
        if total >= required_total:
            share = tuning / total
            if share < TUNING_SHARE_MIN or share > TUNING_SHARE_MAX:
                share_errors.append(
                    f"tuning share for {label} is {share:.3f} outside 0.65 through 0.75"
                )
    errors.extend(sorted(share_errors))

    records = [
        (str(entry.path), entry.split, manifest.root / entry.path) for entry in manifest
    ]
    digest_groups: dict[str, list[str]] = defaultdict(list)
    digest_by_path: dict[str, str] = {}
    for rel, _split, path in records:
        digest = _sha256(path)
        digest_groups[digest].append(rel)
        digest_by_path[rel] = digest

    duplicate_errors: list[str] = []
    for paths in digest_groups.values():
        if len(paths) >= 2:
            for left, right in combinations(sorted(paths), 2):
                duplicate_errors.append(f"duplicate content: {left} and {right}")
    errors.extend(sorted(duplicate_errors))

    features = {rel: _feature(path) for rel, _split, path in records}
    transformed_errors: list[str] = []
    ordered_records = sorted(records, key=lambda item: item[0])
    for left, right in combinations(ordered_records, 2):
        left_rel, left_split, _left_path = left
        right_rel, right_split, _right_path = right
        if left_split == right_split:
            continue
        if digest_by_path[left_rel] == digest_by_path[right_rel]:
            continue
        left_feature = features[left_rel]
        right_feature = features[right_rel]
        if (
            left_feature is not None
            and right_feature is not None
            and _features_match(left_feature, right_feature)
        ):
            transformed_errors.append(
                "possible same-image copy across splits: "
                f"{left_rel} ({left_split}) and {right_rel} ({right_split})"
            )
    errors.extend(sorted(transformed_errors))

    decode_errors: list[str] = []
    for rel, _split, path in sorted(records):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with Image.open(path) as image:
                    width, height = image.size
                    pixels = width * height
                    if pixels > SAFE_MAX_PIXELS:
                        decode_errors.append(f"oversized: {rel} ({pixels} pixels)")
                        continue
                    image.load()
                    expected = _FORMAT_BY_SUFFIX[path.suffix.casefold()]
                    actual = image.format
                    if actual != expected:
                        decode_errors.append(
                            f"format mismatch: {rel} (expected {expected}, found {actual})"
                        )
        except Exception:
            decode_errors.append(f"cannot decode: {rel}")
    errors.extend(sorted(decode_errors))

    result_errors = tuple(errors)
    valid = not result_errors
    return DatasetValidation(valid=valid, exploratory=not valid, errors=result_errors)
