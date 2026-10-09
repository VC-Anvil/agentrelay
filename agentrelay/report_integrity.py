"""Check one local report against its adjacent receipt without following receipt paths."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .snapshots import SnapshotError, _is_link, _read_stable_file, _regular_file, _signature


MAX_ARTIFACT_BYTES = 1_048_576
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def _hex_digest(value):
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate receipt key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def _stable_named_file(directory, filename):
    path, info = _regular_file(directory, (filename,))
    if info.st_size > MAX_ARTIFACT_BYTES:
        raise SnapshotError(f"{filename} exceeds 1 MiB")
    return _read_stable_file(path, info, MAX_ARTIFACT_BYTES)


def verify_report(directory, *, receipt_sha256=None) -> dict:
    """Classify local byte integrity; this neither authenticates nor accepts the work."""
    if receipt_sha256 is not None and not _hex_digest(receipt_sha256):
        raise ValueError("receipt_sha256 must be exactly 64 hexadecimal characters")
    try:
        root = Path(os.path.abspath(Path(directory).expanduser()))
        directory_identities = []
        for component in (*reversed(root.parents), root):
            info = os.lstat(component)
            if _is_link(info, component) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("directory must be an existing real directory")
            identity = _signature(info) if component == root else (info.st_dev, info.st_ino)
            directory_identities.append((component, identity))
    except (TypeError, OSError, RuntimeError) as exc:
        raise ValueError("directory must be an existing real directory") from exc

    expected_receipt = receipt_sha256.lower() if receipt_sha256 is not None else None
    result = {"schema_version": 1, "directory": str(root), "status": "uncheckable",
              "reason": None, "expected_report_sha256": None, "actual_report_sha256": None,
              "receipt_sha256": None, "expected_receipt_sha256": expected_receipt,
              "receipt_matches_expected": None}

    def finish():
        try:
            for component, identity in directory_identities:
                current = os.lstat(component)
                current_identity = (_signature(current) if component == root
                                    else (current.st_dev, current.st_ino))
                if (_is_link(current, component) or not stat.S_ISDIR(current.st_mode)
                        or current_identity != identity):
                    raise SnapshotError("directory changed")
        except (OSError, SnapshotError):
            result.update(status="uncheckable", reason="directory changed during verification",
                          expected_report_sha256=None, actual_report_sha256=None,
                          receipt_sha256=None, receipt_matches_expected=None)
        return result

    try:
        os.lstat(root / "receipt.json")
    except FileNotFoundError:
        result["reason"] = "receipt.json is missing"
        return finish()
    except OSError:
        result["reason"] = "receipt.json cannot be inspected"
        return finish()
    try:
        receipt_bytes = _stable_named_file(root, "receipt.json")
    except (SnapshotError, OSError):
        result["reason"] = "receipt.json is not a stable regular file within 1 MiB"
        return finish()
    initial_receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
    result["receipt_sha256"] = initial_receipt_hash
    if expected_receipt is not None:
        matches = initial_receipt_hash == expected_receipt
        result["receipt_matches_expected"] = matches
        if not matches:
            result["reason"] = "receipt_sha256 does not match expected receipt"
            return finish()

    try:
        receipt = json.loads(receipt_bytes.decode("utf-8", errors="strict"),
                             object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, RecursionError):
        result["reason"] = "receipt.json is invalid JSON"
        return finish()
    if not isinstance(receipt, dict) or not _hex_digest(receipt.get("report_sha256")):
        result["reason"] = "receipt.json has no valid report_sha256"
        return finish()
    expected_report = receipt["report_sha256"].lower()
    result["expected_report_sha256"] = expected_report

    report_path = root / "report.md"
    try:
        os.lstat(report_path)
    except FileNotFoundError:
        result["status"] = "missing"
        result["reason"] = "report.md is missing"
        return finish()
    except OSError:
        result["reason"] = "report.md cannot be inspected"
        return finish()
    try:
        report_bytes = _stable_named_file(root, "report.md")
    except (SnapshotError, OSError):
        result["reason"] = "report.md is not a stable regular file within 1 MiB"
        return finish()
    result["actual_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()

    try:
        receipt_again = _stable_named_file(root, "receipt.json")
    except (SnapshotError, OSError):
        result["reason"] = "receipt.json changed during verification"
        result["receipt_sha256"] = None
        result["receipt_matches_expected"] = None
        return finish()
    if receipt_again != receipt_bytes:
        result["reason"] = "receipt.json changed during verification"
        result["receipt_sha256"] = None
        result["receipt_matches_expected"] = None
        return finish()
    if result["actual_report_sha256"] == expected_report:
        result["status"] = "unchanged"
    else:
        result["status"] = "modified"
        result["reason"] = "report.md hash differs from receipt"
    return finish()
