"""Independent consumer check: emitted hunks reconstruct the captured bytes."""

from pathlib import Path
import random
import tempfile
import unittest

from agentrelay.snapshot_diff import diff_snapshots
from agentrelay.snapshots import create_snapshot


def physical_lines(data):
    pieces = data.split(b"\n")
    return [piece + b"\n" for piece in pieces[:-1]] + ([pieces[-1]] if pieces[-1] else [])


class SnapshotDiffReconstructionTests(unittest.TestCase):
    def test_structured_hunks_reconstruct_exact_after_bytes(self):
        rng = random.Random(1515)
        fixtures = {}
        endings = [b"\n", b"\r\n"]
        for number in range(32):
            # Repeated lines, UTF-8, insertions, removals, replacements and EOF
            # endings exercise the protocol as consumed, not matcher internals.
            before = [rng.choice([b"repeat", b"", "línea λ".encode(), b"lone\rCR", b"tail"])
                      + rng.choice(endings) for _ in range(rng.randrange(3, 32))]
            after = before.copy()
            for _ in range(rng.randrange(1, 7)):
                position = rng.randrange(len(after) + 1)
                action = rng.randrange(3)
                if action == 0:
                    after.insert(position, b"inserted" + rng.choice(endings))
                elif position < len(after) and action == 1:
                    del after[position]
                elif position < len(after):
                    after[position] = b"replaced" + rng.choice(endings)
            if number % 2 and before:
                before[-1] = before[-1].rstrip(b"\r\n")
            if number % 3 and after:
                after[-1] = after[-1].rstrip(b"\r\n")
            fixtures[f"case-{number:02}.txt"] = (b"".join(before), b"".join(after))
        fixtures.update({"empty-add.txt": (b"", b"new"),
                         "empty-remove.txt": (b"old\n", b""),
                         "same.txt": (b"same\r\n", b"same\r\n"),
                         "only-ending.txt": (b"same\n", b"same\r\n")})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            for name, (before, _) in fixtures.items():
                (source / name).write_bytes(before)
            old = create_snapshot(source, list(fixtures), root / "before")
            for name, (_, after) in fixtures.items():
                (source / name).write_bytes(after)
            new = create_snapshot(source, list(fixtures), root / "after")
            result = diff_snapshots(root / "before", root / "after",
                expected_before_id=old["snapshot_id"], expected_after_id=new["snapshot_id"])
            self.assertEqual(result["summary"]["diff_omitted"], 0)
            for entry in result["files"]:
                with self.subTest(path=entry["path"]):
                    before, after = fixtures[entry["path"]]
                    if before == after:
                        self.assertEqual(entry["diff"]["status"], "not_needed")
                        continue
                    self.assertEqual(entry["diff"]["status"], "available")
                    original = physical_lines(before)
                    output = []
                    cursor = 0
                    for hunk in entry["diff"]["hunks"]:
                        self.assertGreaterEqual(hunk["before_start"], cursor)
                        output.extend(original[cursor:hunk["before_start"]])
                        self.assertEqual(len(output), hunk["after_start"])
                        cursor = hunk["before_start"]
                        emitted = 0
                        for line in hunk["lines"]:
                            raw = line["text"].encode("utf-8") + {
                                "lf": b"\n", "crlf": b"\r\n", "none": b""}[line["eol"]]
                            if line["kind"] in ("context", "removed"):
                                self.assertEqual(original[cursor], raw)
                                cursor += 1
                            if line["kind"] in ("context", "added"):
                                output.append(raw)
                                emitted += 1
                        self.assertEqual(cursor - hunk["before_start"], hunk["before_count"])
                        self.assertEqual(emitted, hunk["after_count"])
                    output.extend(original[cursor:])
                    self.assertEqual(b"".join(output), after)


if __name__ == "__main__":
    unittest.main()
