"""Bounded, read-only project input snapshots with self-verifying manifests.

A snapshot is not an atomic multi-file filesystem view. Each selected file is
checked before and after its own read, so an individual concurrent change is
rejected, but files may legitimately have been captured at slightly different
instants. Verification detects accidental corruption; the unsigned manifest is
not authentication, and these checks are not a sandbox against a hostile local
process racing filesystem operations.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import tempfile


SCHEMA_VERSION = 1
MAX_FILES = 64
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 8_388_608
MAX_MANIFEST_BYTES = 1_048_576
_HASH_PREFIX = b"agentrelay.snapshot.v1\0"
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class SnapshotError(ValueError):
    """A requested snapshot or supplied snapshot directory is invalid."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _canonical_relative(value: str) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SnapshotError("file paths must be nonempty strings")
    if any(character in value for character in "*?[]"):
        raise SnapshotError(f"globs are not allowed: {value!r}")
    if PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive:
        raise SnapshotError(f"absolute paths are not allowed: {value!r}")
    normalized = value.replace("\\", "/")
    if PurePosixPath(normalized).is_absolute():
        raise SnapshotError(f"absolute paths are not allowed: {value!r}")
    raw_parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise SnapshotError(f"path traversal or ambiguous components are not allowed: {value!r}")
    for part in raw_parts:
        if ":" in part or any(ord(character) < 32 or character in '<>"|' for character in part):
            raise SnapshotError(f"path contains a Windows-unsafe component: {value!r}")
        if part.endswith((" ", ".")):
            raise SnapshotError(f"path contains a Windows-unsafe component: {value!r}")
        if part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED:
            raise SnapshotError(f"path contains a reserved Windows name: {value!r}")
    canonical = "/".join(raw_parts)
    return canonical, tuple(raw_parts)


def _signature(info: os.stat_result) -> tuple[int, ...]:
    # Python 3.12 on Windows can expose creation time as st_ctime_ns from a path
    # stat but change time from an open handle. They describe the same unchanged
    # file, so ctime is only a portable stability signal on non-Windows systems.
    common = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return common if os.name == "nt" else (*common, info.st_ctime_ns)


def _is_link(info: os.stat_result, path: Path) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse and attributes & reparse) or path.is_symlink()


def _regular_file(root: Path, parts: tuple[str, ...]) -> tuple[Path, os.stat_result]:
    current = root
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise SnapshotError(f"cannot inspect source path {current}: {exc.strerror or type(exc).__name__}") from exc
        if _is_link(info, current):
            raise SnapshotError(f"symlinks are not allowed: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise SnapshotError(f"path component is not a directory: {current}")
    if not stat.S_ISREG(info.st_mode):
        raise SnapshotError(f"source is not a regular file: {current}")
    return current, info


def _read_stable_file(path: Path, before: os.stat_result, limit: int = MAX_FILE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SnapshotError(f"cannot open file without following links: {path}") from exc
    chunks: list[bytes] = []
    size = 0
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _signature(opened) != _signature(before):
            raise SnapshotError(f"file changed before reading: {path}")
        while True:
            chunk = os.read(descriptor, min(131_072, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise SnapshotError(f"file exceeds {MAX_FILE_BYTES} bytes: {path}")
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_after = os.lstat(path)
    except OSError as exc:
        raise SnapshotError(f"file disappeared while reading: {path}") from exc
    if (not stat.S_ISREG(path_after.st_mode) or _is_link(path_after, path)
            or _signature(opened_after) != _signature(before)
            or _signature(path_after) != _signature(before)):
        raise SnapshotError(f"file changed while reading: {path}")
    return b"".join(chunks)


def _content_entry(digest, relative: str, data: bytes) -> None:
    encoded = relative.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


def _prepare_source(root: Path, files: list[str]) -> tuple[Path, list[tuple[str, tuple[str, ...], Path, os.stat_result]]]:
    root = Path(root)
    if not root.exists() or not root.is_dir():
        raise SnapshotError("source root must be an existing real directory")
    root_info = os.lstat(root)
    if _is_link(root_info, root):
        raise SnapshotError("source root must be an existing real directory")
    root = root.resolve(strict=True)
    if not isinstance(files, list) or not files:
        raise SnapshotError("files must be a nonempty list")
    if len(files) > MAX_FILES:
        raise SnapshotError(f"snapshot supports at most {MAX_FILES} files")
    prepared = []
    seen = set()
    total = 0
    for value in files:
        relative, parts = _canonical_relative(value)
        identity = relative.casefold()
        if identity in seen:
            raise SnapshotError(f"duplicate file path: {relative}")
        seen.add(identity)
        source, info = _regular_file(root, parts)
        try:
            source.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise SnapshotError(f"source path escapes root: {relative}") from exc
        if info.st_size > MAX_FILE_BYTES:
            raise SnapshotError(f"file exceeds {MAX_FILE_BYTES} bytes: {relative}")
        total += info.st_size
        if total > MAX_TOTAL_BYTES:
            raise SnapshotError(f"snapshot exceeds {MAX_TOTAL_BYTES} bytes")
        prepared.append((relative, parts, source, info))
    return root, sorted(prepared, key=lambda item: item[0])


def _remove_owned_staging(staging: Path, expected_parent: Path) -> None:
    """Remove only the real staging directory created directly in our parent."""
    try:
        info = os.lstat(staging)
        if _is_link(info, staging) or not stat.S_ISDIR(info.st_mode):
            return
        resolved = staging.resolve(strict=True)
        if resolved.parent != expected_parent:
            return
        shutil.rmtree(resolved)
    except OSError:
        # A hostile concurrent replacement can prevent safe cleanup. Leaving a
        # non-promoted staging path is safer than following an uncertain path.
        return


def create_snapshot(root: Path, files: list[str], destination: Path) -> dict:
    """Copy explicit project files into a new bounded snapshot directory.

    The source project is only read. ``destination.parent`` must already exist,
    and the destination itself must be new and outside the source root.
    """
    source_root, prepared = _prepare_source(Path(root), files)
    requested = Path(destination)
    if requested.name in ("", ".", ".."):
        raise SnapshotError("destination must name a new directory")
    parent = requested.parent
    if not parent.exists() or not parent.is_dir():
        raise SnapshotError("destination parent must be an existing directory")
    parent = parent.resolve(strict=True)
    destination = parent / requested.name
    if _lexists(destination):
        raise FileExistsError(f"snapshot destination already exists: {destination}")
    if _is_within(destination, source_root):
        raise SnapshotError("snapshot destination must be outside the source root")

    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=parent))
    promoted = False
    try:
        files_root = staging / "files"
        files_root.mkdir()
        digest = hashlib.sha256(_HASH_PREFIX)
        manifest_files = []
        actual_total = 0
        for relative, parts, source, before in prepared:
            data = _read_stable_file(source, before)
            actual_total += len(data)
            if actual_total > MAX_TOTAL_BYTES:
                raise SnapshotError(f"snapshot exceeds {MAX_TOTAL_BYTES} bytes")
            target = files_root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            file_hash = hashlib.sha256(data).hexdigest()
            manifest_files.append({"path": relative, "size": len(data), "sha256": file_hash})
            _content_entry(digest, relative, data)
        content_hash = digest.hexdigest()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": f"sha256:{content_hash}",
            "content_sha256": content_hash,
            "captured_at": _utc(),
            "source_root": str(source_root),
            "files": manifest_files,
        }
        manifest_data = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if len(manifest_data) > MAX_MANIFEST_BYTES:
            raise SnapshotError("manifest exceeds its size limit")
        with (staging / "manifest.json").open("xb") as stream:
            stream.write(manifest_data)
        if _lexists(destination):
            raise FileExistsError(f"snapshot destination appeared during creation: {destination}")
        os.rename(staging, destination)
        promoted = True
        return manifest
    finally:
        if not promoted and _lexists(staging):
            _remove_owned_staging(staging, parent)


def _invalid(*errors: str, snapshot_id=None) -> dict:
    return {"valid": False, "errors": list(errors), "snapshot_id": snapshot_id}


def verify_snapshot(directory: Path) -> dict:
    """Verify a snapshot without trusting source_root or manifest file paths."""
    directory = Path(directory)
    errors: list[str] = []
    manifest = None
    snapshot_id = None
    try:
        if not directory.exists() or not directory.is_dir():
            return _invalid("snapshot directory must be an existing real directory")
        directory_info = os.lstat(directory)
        if _is_link(directory_info, directory):
            return _invalid("snapshot directory must be an existing real directory")
        directory = directory.resolve(strict=True)
        manifest_path = directory / "manifest.json"
        try:
            manifest_info = os.lstat(manifest_path)
        except OSError:
            return _invalid("manifest.json is missing")
        if _is_link(manifest_info, manifest_path) or not stat.S_ISREG(manifest_info.st_mode):
            return _invalid("manifest.json must be a regular non-symlink file")
        if manifest_info.st_size > MAX_MANIFEST_BYTES:
            return _invalid("manifest.json exceeds its size limit")
        try:
            manifest = json.loads(_read_stable_file(manifest_path, manifest_info, MAX_MANIFEST_BYTES))
        except (UnicodeError, json.JSONDecodeError, SnapshotError) as exc:
            return _invalid(f"manifest.json is invalid: {exc}")
        if not isinstance(manifest, dict):
            return _invalid("manifest must be a JSON object")
        snapshot_id = manifest.get("snapshot_id")
        expected_fields = {"schema_version", "snapshot_id", "content_sha256", "captured_at", "source_root", "files"}
        if set(manifest) != expected_fields:
            errors.append("manifest has missing or unexpected fields")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            errors.append("unsupported schema_version")
        if not isinstance(manifest.get("captured_at"), str) or not manifest["captured_at"]:
            errors.append("captured_at must be a nonempty string")
        if not isinstance(manifest.get("source_root"), str) or not manifest["source_root"]:
            errors.append("source_root must be a nonempty string")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            return _invalid(*errors, "files must be an array", snapshot_id=snapshot_id)
        if not entries:
            errors.append("files must not be empty")
        if len(entries) > MAX_FILES:
            errors.append(f"manifest exceeds {MAX_FILES} files")
            entries = entries[:MAX_FILES]
        files_root = directory / "files"
        try:
            root_info = os.lstat(files_root)
            if _is_link(root_info, files_root) or not stat.S_ISDIR(root_info.st_mode):
                errors.append("files must be a real directory")
                return {"valid": False, "errors": errors, "snapshot_id": snapshot_id}
        except OSError:
            errors.append("files directory is missing")
            return {"valid": False, "errors": errors, "snapshot_id": snapshot_id}
        files_root = files_root.resolve(strict=True)

        seen = set()
        prepared = []
        declared_total = 0
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
                errors.append(f"files[{index}] has invalid fields")
                continue
            try:
                relative, parts = _canonical_relative(entry["path"])
            except SnapshotError as exc:
                errors.append(f"files[{index}]: {exc}")
                continue
            identity = relative.casefold()
            if identity in seen:
                errors.append(f"duplicate manifest path: {relative}")
                continue
            seen.add(identity)
            size = entry["size"]
            checksum = entry["sha256"]
            if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE_BYTES:
                errors.append(f"invalid size for {relative}")
                continue
            if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
                errors.append(f"invalid sha256 for {relative}")
                continue
            declared_total += size
            if declared_total > MAX_TOTAL_BYTES:
                errors.append(f"manifest exceeds {MAX_TOTAL_BYTES} bytes")
                continue
            prepared.append((relative, parts, size, checksum))

        digest = hashlib.sha256(_HASH_PREFIX)
        all_content_read = len(prepared) == len(entries)
        actual_total = 0
        for relative, parts, expected_size, expected_hash in sorted(prepared):
            try:
                path, info = _regular_file(files_root, parts)
                try:
                    path.resolve(strict=True).relative_to(files_root)
                except ValueError as exc:
                    raise SnapshotError("file path escapes files directory") from exc
                if info.st_size > MAX_FILE_BYTES:
                    raise SnapshotError("file exceeds its size limit")
                data = _read_stable_file(path, info)
            except SnapshotError as exc:
                errors.append(f"{relative}: {exc}")
                all_content_read = False
                continue
            actual_total += len(data)
            if actual_total > MAX_TOTAL_BYTES:
                errors.append(f"snapshot content exceeds {MAX_TOTAL_BYTES} bytes")
                all_content_read = False
            actual_hash = hashlib.sha256(data).hexdigest()
            if len(data) != expected_size:
                errors.append(f"size mismatch for {relative}")
            if actual_hash != expected_hash:
                errors.append(f"sha256 mismatch for {relative}")
            _content_entry(digest, relative, data)
        if all_content_read:
            calculated = digest.hexdigest()
            if manifest.get("content_sha256") != calculated:
                errors.append("content_sha256 mismatch")
            if snapshot_id != f"sha256:{calculated}":
                errors.append("snapshot_id mismatch")
        return {"valid": not errors, "errors": errors, "snapshot_id": snapshot_id}
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f"verification failed safely: {type(exc).__name__}: {exc}")
        return {"valid": False, "errors": errors, "snapshot_id": snapshot_id}
