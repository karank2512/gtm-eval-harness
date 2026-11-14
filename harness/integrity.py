"""Hashing and canonical-serialisation helpers shared by the v2 world path.

These hashes are CONSISTENCY links, not a security boundary: they let the
offline grader notice that a dataset, plan, world database or log is not
the one a run was sealed with. Anyone who can rewrite the local files can
also recompute every hash, so nothing here is tamperproof against the
machine's owner or an administrator.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Tuple


class IntegrityError(RuntimeError):
    """An artifact is missing, inconsistent, or not the one that was sealed."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(obj: Any) -> str:
    """One deterministic text form per JSON value (sorted keys, no spaces)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def sha256_canonical(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def git_blob_sha1(data: bytes) -> str:
    """The id git gives a blob with these exact bytes (sha1 object format)."""
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def combined_hash(pins: Dict[str, str]) -> str:
    """One hash over a {path: sha256} map, independent of dict order."""
    return sha256_canonical(sorted(pins.items()))


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    """Strict JSONL: every non-blank line must be one JSON object."""
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IntegrityError(
                    f"{path}:{lineno}: not valid JSON ({exc})") from exc
            if not isinstance(obj, dict):
                raise IntegrityError(f"{path}:{lineno}: not a JSON object")
            rows.append(obj)
    return rows


def find_duplicates(values: Iterable[Any]) -> List[Any]:
    seen = set()
    dupes = []
    for value in values:
        if value in seen and value not in dupes:
            dupes.append(value)
        seen.add(value)
    return dupes


def inventory_diff(expected: Iterable[Any], actual: Iterable[Any]
                   ) -> Tuple[List[Any], List[Any], List[Any]]:
    """(missing, extra, duplicated) of `actual` against `expected`."""
    actual = list(actual)
    expected_set = set(expected)
    actual_set = set(actual)
    return (sorted(expected_set - actual_set),
            sorted(actual_set - expected_set),
            sorted(find_duplicates(actual)))
