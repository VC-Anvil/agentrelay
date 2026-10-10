"""Bounded, structured differences between two verified frozen snapshots.

Only snapshot manifests and selected files below their ``files`` directories are
read. Manifest ``source_root`` values and document links are provenance, not
instructions to inspect a live project.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import snapshots as _snapshots
from .freshness import _verified_manifest


SnapshotError = _snapshots.SnapshotError
MAX_LINES = 50_000
MAX_COMPARISON_PRODUCT = 1_000_000
MAX_HUNKS_BYTES = 32_768
MAX_TOTAL_HUNKS_BYTES = 131_072
MAX_REPORT_BYTES = 1_048_576
CONTEXT_LINES = 3
_SNAPSHOT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")

# A separate alias permits focused stable-read fault injection without altering
# snapshot verification performed by _verified_manifest.
_read_file = _snapshots._read_stable_file


def _canonical_bytes(value) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SnapshotError("diff report cannot be serialized safely") from exc


def _selectors(paths) -> list[str] | None:
    if paths is None:
        return None
    if not isinstance(paths, list) or not 1 <= len(paths) <= 128:
        raise SnapshotError("paths must be a nonempty list of at most 128 relative paths")
    selected: list[str] = []
    seen: set[str] = set()
    for value in paths:
        relative, _ = _snapshots._canonical_relative(value)
        identity = relative
        if identity in seen:
            raise SnapshotError(f"duplicate selected path: {relative}")
        seen.add(identity)
        selected.append(relative)
    return sorted(selected)


def _identity(value, name: str) -> str:
    if not isinstance(value, str) or _SNAPSHOT_ID.fullmatch(value) is None:
        raise SnapshotError(f"{name} must be sha256: plus 64 lowercase hex characters")
    return value


def _directory_signature(path: Path) -> tuple[int, ...]:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise SnapshotError(f"snapshot directory changed: {path}") from exc
    if _snapshots._is_link(info, path) or not stat.S_ISDIR(info.st_mode):
        raise SnapshotError(f"snapshot directory is unsafe: {path}")
    return _snapshots._signature(info)


def _side(directory, expected_id: str) -> dict:
    try:
        requested = Path(directory)
        directory_signature = _directory_signature(requested)
        files_signature = _directory_signature(requested / "files")
        resolved, manifest = _verified_manifest(requested)
        if manifest["snapshot_id"] != expected_id:
            raise SnapshotError("snapshot_id does not match expected identity")
        files_root = resolved / "files"
        if (_directory_signature(resolved) != directory_signature
                or _directory_signature(files_root) != files_signature):
            raise SnapshotError("snapshot directory changed during verification")
        side = {"directory": resolved, "directory_signature": directory_signature,
                "files_root": files_root, "files_signature": files_signature,
                "entries": {entry["path"]: entry for entry in manifest["files"]}}
        return side
    except SnapshotError:
        raise
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise SnapshotError(f"cannot verify snapshot safely: {type(exc).__name__}") from exc


def _confirm_side(side: dict) -> None:
    if (_directory_signature(side["directory"]) != side["directory_signature"]
            or _directory_signature(side["files_root"]) != side["files_signature"]):
        raise SnapshotError("snapshot directory changed during diff")


def _selected_bytes(side: dict, relative: str) -> bytes:
    _confirm_side(side)
    entry = side["entries"][relative]
    _, parts = _snapshots._canonical_relative(relative)
    files_root = side["files_root"]
    path, info = _snapshots._regular_file(files_root, parts)
    try:
        path.resolve(strict=True).relative_to(files_root)
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"snapshot path escapes or changed: {relative}") from exc
    if info.st_size > _snapshots.MAX_FILE_BYTES:
        raise SnapshotError(f"snapshot file exceeds its size limit: {relative}")
    try:
        data = _read_file(path, info, _snapshots.MAX_FILE_BYTES)
    except SnapshotError:
        raise
    except OSError as exc:
        raise SnapshotError(f"cannot read snapshot file safely: {relative}") from exc
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise SnapshotError(f"snapshot file changed after verification: {relative}")
    _confirm_side(side)
    return data


def _lines(data: bytes) -> tuple[list[tuple[str, str]] | None, str | None]:
    if b"\x00" in data:
        return None, "binary"
    try:
        value = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, "invalid_utf8"
    if not value:
        return [], None
    line_count = value.count("\n") + (0 if value.endswith("\n") else 1)
    if line_count > MAX_LINES:
        return None, "line_limit"
    parts = value.split("\n")
    terminated = value.endswith("\n")
    lines: list[tuple[str, str]] = []
    for part in parts[:-1]:
        if part.endswith("\r"):
            lines.append((part[:-1], "crlf"))
        else:
            lines.append((part, "lf"))
    if not terminated:
        lines.append((parts[-1], "none"))
    return lines, None


def _line(kind: str, value: tuple[str, str]) -> dict:
    return {"kind": kind, "text": value[0], "eol": value[1]}


def _hunks(before: list[tuple[str, str]], after: list[tuple[str, str]]) -> tuple[list[dict] | None, str | None]:
    if len(before) > MAX_LINES or len(after) > MAX_LINES:
        return None, "line_limit"

    prefix = 0
    while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(before), len(after)) - prefix
           and before[len(before) - suffix - 1] == after[len(after) - suffix - 1]):
        suffix += 1
    before_offset = max(0, prefix - CONTEXT_LINES)
    after_offset = max(0, prefix - CONTEXT_LINES)
    before_end = len(before) - max(0, suffix - CONTEXT_LINES)
    after_end = len(after) - max(0, suffix - CONTEXT_LINES)
    before_window = before[before_offset:before_end]
    after_window = after[after_offset:after_end]
    if len(before_window) * len(after_window) > MAX_COMPARISON_PRODUCT:
        return None, "comparison_limit"

    matcher = difflib.SequenceMatcher(None, before_window, after_window, autojunk=False)
    hunks: list[dict] = []
    for group in matcher.get_grouped_opcodes(CONTEXT_LINES):
        first, last = group[0], group[-1]
        lines: list[dict] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines.extend(_line("context", value) for value in before_window[i1:i2])
            else:
                if tag in ("replace", "delete"):
                    lines.extend(_line("removed", value) for value in before_window[i1:i2])
                if tag in ("replace", "insert"):
                    lines.extend(_line("added", value) for value in after_window[j1:j2])
        hunks.append({"before_start": before_offset + first[1],
                      "before_count": last[2] - first[1],
                      "after_start": after_offset + first[3],
                      "after_count": last[4] - first[3], "lines": lines})
    return hunks, None


def _difference(before_data: bytes, after_data: bytes,
                available_bytes: int) -> tuple[dict, int]:
    before_lines, reason = _lines(before_data)
    if reason is None:
        after_lines, reason = _lines(after_data)
    if reason is not None:
        return {"status": "omitted", "reason": reason, "hunks": []}, 0
    hunks, reason = _hunks(before_lines, after_lines)
    if reason is not None:
        return {"status": "omitted", "reason": reason, "hunks": []}, 0
    size = len(_canonical_bytes(hunks))
    if size > MAX_HUNKS_BYTES or available_bytes + size > MAX_TOTAL_HUNKS_BYTES:
        return {"status": "omitted", "reason": "output_limit", "hunks": []}, 0
    return {"status": "available", "reason": None, "hunks": hunks}, size


def diff_snapshots(before, after, *, expected_before_id, expected_after_id,
                   paths=None) -> dict:
    """Compare only frozen snapshot bytes; return complete bounded JSON hunks."""
    expected_before_id = _identity(expected_before_id, "expected_before_id")
    expected_after_id = _identity(expected_after_id, "expected_after_id")
    selection = _selectors(paths)
    before_side = _side(before, expected_before_id)
    after_side = _side(after, expected_after_id)
    known = set(before_side["entries"]) | set(after_side["entries"])
    if selection is None:
        selection = sorted(known)
    else:
        unknown = set(selection) - known
        if unknown:
            raise SnapshotError(f"selected path is absent from both snapshots: {min(unknown)}")

    files: list[dict] = []
    summary = {"total": len(selection), "unchanged": 0, "modified": 0,
               "added": 0, "removed": 0, "diff_available": 0, "diff_omitted": 0}
    available_bytes = 0
    for relative in selection:
        before_entry = before_side["entries"].get(relative)
        after_entry = after_side["entries"].get(relative)
        before_data = _selected_bytes(before_side, relative) if before_entry is not None else b""
        after_data = _selected_bytes(after_side, relative) if after_entry is not None else b""
        before_meta = ({"size": before_entry["size"], "sha256": before_entry["sha256"]}
                       if before_entry is not None else None)
        after_meta = ({"size": after_entry["size"], "sha256": after_entry["sha256"]}
                      if after_entry is not None else None)
        if before_entry is None:
            status = "added"
        elif after_entry is None:
            status = "removed"
        elif before_meta == after_meta:
            status = "unchanged"
        else:
            status = "modified"
        if status == "unchanged":
            difference = {"status": "not_needed", "reason": None, "hunks": []}
        else:
            difference, used = _difference(before_data, after_data, available_bytes)
            available_bytes += used
            summary["diff_" + difference["status"]] += 1
        summary[status] += 1
        files.append({"path": relative, "status": status,
                      "before": before_meta, "after": after_meta, "diff": difference})
    _confirm_side(before_side)
    _confirm_side(after_side)
    report = {"schema_version": 1, "before_snapshot_id": expected_before_id,
              "after_snapshot_id": expected_after_id, "files": files, "summary": summary}
    if len(_canonical_bytes(report)) > MAX_REPORT_BYTES:
        raise SnapshotError("diff report exceeds 1 MiB; select fewer --file paths")
    return report
