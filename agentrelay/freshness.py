"""Compare a verified input snapshot with an explicitly selected current root.

The manifest's ``source_root`` is provenance only.  It is never used to select
or authorize current files.  Comparisons are read-only, bounded like snapshot
creation, and stable per file rather than atomic across the whole project.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from . import snapshots as _snapshots


SnapshotError = _snapshots.SnapshotError
MAX_FILE_BYTES = _snapshots.MAX_FILE_BYTES
MAX_TOTAL_BYTES = _snapshots.MAX_TOTAL_BYTES
MAX_MANIFEST_BYTES = _snapshots.MAX_MANIFEST_BYTES

# Local aliases keep comparison-specific fault injection separate from snapshot
# verification in tests while retaining the snapshot module's exact rules.
_is_link = _snapshots._is_link
_read_current_file = _snapshots._read_stable_file


def _invalid_snapshot(result: dict) -> SnapshotError:
    errors = result.get("errors") if isinstance(result, dict) else None
    detail = "; ".join(str(error) for error in errors) if isinstance(errors, list) and errors else "verification failed"
    return SnapshotError(f"invalid snapshot: {detail}")


def _read_manifest_once(directory: Path) -> tuple[Path, tuple[int, ...], bytes]:
    """Read the manifest stably and retain the directory identity around it."""
    try:
        info = os.lstat(directory)
        if _is_link(info, directory) or not stat.S_ISDIR(info.st_mode):
            raise SnapshotError("snapshot directory must be an existing real directory")
        resolved = directory.resolve(strict=True)
        resolved_info = os.lstat(resolved)
        if (_is_link(resolved_info, resolved) or not stat.S_ISDIR(resolved_info.st_mode)
                or _snapshots._signature(resolved_info) != _snapshots._signature(info)):
            raise SnapshotError("snapshot directory changed while reading its manifest")
        manifest_path = resolved / "manifest.json"
        manifest_info = os.lstat(manifest_path)
        if _is_link(manifest_info, manifest_path) or not stat.S_ISREG(manifest_info.st_mode):
            raise SnapshotError("manifest.json must be a regular non-symlink file")
        if manifest_info.st_size > MAX_MANIFEST_BYTES:
            raise SnapshotError("manifest.json exceeds its size limit")
        data = _snapshots._read_stable_file(manifest_path, manifest_info, MAX_MANIFEST_BYTES)
        after = os.lstat(resolved)
        if (_is_link(after, resolved) or not stat.S_ISDIR(after.st_mode)
                or _snapshots._signature(after) != _snapshots._signature(resolved_info)):
            raise SnapshotError("snapshot directory changed while reading its manifest")
        return resolved, _snapshots._signature(after), data
    except SnapshotError:
        raise
    except OSError as exc:
        raise SnapshotError(f"cannot read snapshot manifest safely: {exc.strerror or type(exc).__name__}") from exc


def _verified_manifest(directory: Path) -> tuple[Path, dict]:
    """Bracket manifest loading with full verification and identity checks."""
    requested = Path(directory)
    before = _snapshots.verify_snapshot(requested)
    if not before.get("valid"):
        raise _invalid_snapshot(before)

    resolved, directory_signature, first_bytes = _read_manifest_once(requested)
    try:
        manifest = json.loads(first_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid snapshot: manifest.json is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("snapshot_id") != before.get("snapshot_id"):
        raise SnapshotError("snapshot identity changed while reading its manifest")

    after = _snapshots.verify_snapshot(resolved)
    if not after.get("valid"):
        raise SnapshotError("snapshot changed during comparison: " + "; ".join(after.get("errors") or ["verification failed"]))
    if after.get("snapshot_id") != before.get("snapshot_id"):
        raise SnapshotError("snapshot identity changed during comparison")

    resolved_again, signature_again, second_bytes = _read_manifest_once(resolved)
    if (resolved_again != resolved or signature_again != directory_signature
            or second_bytes != first_bytes):
        raise SnapshotError("snapshot manifest changed during comparison")
    return resolved, manifest


def _prepare_current_root(root: Path) -> tuple[Path, tuple[int, ...]]:
    requested = Path(root)
    try:
        info = os.lstat(requested)
        if _is_link(info, requested) or not stat.S_ISDIR(info.st_mode):
            raise SnapshotError("current root must be an existing real directory")
        resolved = requested.resolve(strict=True)
        resolved_info = os.lstat(resolved)
        if (_is_link(resolved_info, resolved) or not stat.S_ISDIR(resolved_info.st_mode)
                or _snapshots._signature(resolved_info) != _snapshots._signature(info)):
            raise SnapshotError("current root changed while being selected")
        return resolved, _snapshots._signature(resolved_info)
    except SnapshotError:
        raise
    except OSError as exc:
        raise SnapshotError(f"cannot inspect current root safely: {exc.strerror or type(exc).__name__}") from exc


def _confirm_missing(path: Path, parent: Path, parent_before: os.stat_result) -> tuple[str, str]:
    """Confirm absence without resolving or following the absent path."""
    try:
        parent_after = os.lstat(parent)
        if (_is_link(parent_after, parent) or not stat.S_ISDIR(parent_after.st_mode)
                or _snapshots._signature(parent_after) != _snapshots._signature(parent_before)):
            return "uncheckable", "parent directory changed while confirming absence"
        try:
            appeared = os.lstat(path)
        except FileNotFoundError:
            return "missing", "path is absent"
        except OSError as exc:
            return "uncheckable", f"cannot confirm absence safely: {exc.strerror or type(exc).__name__}"
        if _is_link(appeared, path):
            return "uncheckable", "unsafe link or reparse point appeared while confirming absence"
        return "uncheckable", "path appeared while confirming absence"
    except OSError as exc:
        return "uncheckable", f"cannot inspect parent while confirming absence: {exc.strerror or type(exc).__name__}"


def _locate_current(root: Path, root_info: os.stat_result, parts: tuple[str, ...]):
    current = root
    parent_info = root_info
    for index, part in enumerate(parts):
        parent = current
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            status, reason = _confirm_missing(current, parent, parent_info)
            return None, None, status, reason
        except OSError as exc:
            return None, None, "uncheckable", f"cannot inspect current path: {exc.strerror or type(exc).__name__}"
        if _is_link(info, current):
            return None, None, "uncheckable", "unsafe symlink, junction, or reparse point"
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            return None, None, "uncheckable", "path component is not a directory"
        parent_info = info
    if not stat.S_ISREG(info.st_mode):
        return None, None, "uncheckable", "current path is not a regular file"
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        return None, None, "uncheckable", f"current path escapes or cannot be resolved safely: {exc}"
    return current, info, None, None


def _empty_current() -> dict:
    return {"size": None, "sha256": None}


def _summary(entries: list[dict]) -> dict:
    result = {"total": len(entries), "unchanged": 0, "modified": 0, "missing": 0, "uncheckable": 0}
    for entry in entries:
        result[entry["status"]] += 1
    return result


def _root_still_same(root: Path, expected_signature: tuple[int, ...]) -> bool:
    try:
        info = os.lstat(root)
        return (not _is_link(info, root) and stat.S_ISDIR(info.st_mode)
                and _snapshots._signature(info) == expected_signature)
    except OSError:
        return False


def compare_snapshot(directory: Path, root: Path) -> dict:
    """Compare verified snapshot entries with files below explicit ``root``.

    An invalid or changing snapshot raises :class:`SnapshotError` before the
    current root is inspected.  Individual current paths that cannot be read
    safely are reported as ``uncheckable`` rather than being confused with
    files that are observably absent.
    """
    _, manifest = _verified_manifest(Path(directory))
    current_root, root_signature = _prepare_current_root(Path(root))
    root_info = os.lstat(current_root)

    entries: list[dict] = []
    bytes_reserved = 0
    for expected_entry in manifest["files"]:
        relative, parts = _snapshots._canonical_relative(expected_entry["path"])
        expected = {"size": expected_entry["size"], "sha256": expected_entry["sha256"]}
        result = {
            "path": relative,
            "status": "uncheckable",
            "expected": expected,
            "current": _empty_current(),
            "reason": "not inspected",
        }
        path, info, early_status, reason = _locate_current(current_root, root_info, parts)
        if early_status:
            result["status"] = early_status
            result["reason"] = reason
            entries.append(result)
            continue
        if info.st_size > MAX_FILE_BYTES:
            result["reason"] = f"current file exceeds {MAX_FILE_BYTES} bytes"
            entries.append(result)
            continue
        if bytes_reserved + info.st_size > MAX_TOTAL_BYTES:
            result["reason"] = f"comparison would exceed {MAX_TOTAL_BYTES} bytes"
            entries.append(result)
            continue
        # Reserve the observed size before I/O.  A failed or racing read still
        # consumes comparison budget, so repeated failures cannot each attempt
        # another full-sized file beyond the aggregate bound.  Using the
        # observed size as the per-read limit also detects growth with the
        # stable reader's one-byte overflow probe.
        bytes_reserved += info.st_size
        try:
            data = _read_current_file(path, info, info.st_size)
        except (SnapshotError, OSError) as exc:
            result["reason"] = f"current file is unstable or unsafe: {exc}"
            entries.append(result)
            continue
        checksum = hashlib.sha256(data).hexdigest()
        current = {"size": len(data), "sha256": checksum}
        result["current"] = current
        size_matches = current["size"] == expected["size"]
        hash_matches = current["sha256"] == expected["sha256"]
        if size_matches and hash_matches:
            result["status"] = "unchanged"
            result["reason"] = "size and sha256 match"
        else:
            result["status"] = "modified"
            if size_matches:
                result["reason"] = "sha256 differs"
            elif hash_matches:
                result["reason"] = "size differs"
            else:
                result["reason"] = "size and sha256 differ"
        entries.append(result)

    if not _root_still_same(current_root, root_signature):
        for entry in entries:
            entry["status"] = "uncheckable"
            entry["current"] = _empty_current()
            entry["reason"] = "current root changed during comparison"

    return {
        "snapshot_id": manifest["snapshot_id"],
        "root": str(current_root),
        "files": entries,
        "summary": _summary(entries),
    }
