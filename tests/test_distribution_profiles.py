"""Check declared-order source packing without a simulator or task score."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from powergrid_bench.distribution.profiles import pack_profiles


class ProfilePackingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def source(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_packing_is_load_major_and_preserves_declared_order(self):
        first = self.source("a.csv", "0\n1\n2\n")
        second = self.source("b.csv", "3\n4\n5\n6\n7\n8\n9\n")
        packed = pack_profiles([first, second], load_count=2, horizon=2)
        self.assertEqual(packed.profiles, (((0.0, 1.0), (4.0, 5.0)), ((2.0, 3.0), (6.0, 7.0))))
        reordered = pack_profiles([second, first], load_count=2, horizon=2)
        self.assertEqual(reordered.profiles[0], ((3.0, 4.0), (7.0, 8.0)))
        self.assertNotEqual(
            packed.manifest["packed_values_sha256"], reordered.manifest["packed_values_sha256"]
        )
        self.assertEqual(packed, pack_profiles([first, second], load_count=2, horizon=2))

    def test_manifest_maps_cross_file_slices_and_unused_tail(self):
        first = self.source("a.csv", "0\n1\n2\n")
        second = self.source("b.csv", "3\n4\n5\n6\n7\n8\n9\n")
        manifest = pack_profiles([first, second], load_count=2, horizon=2).manifest
        self.assertEqual(manifest["profile_count"], 2)
        self.assertEqual(manifest["source_rows"], 10)
        self.assertEqual(manifest["used_rows"], 8)
        self.assertEqual(manifest["unused_rows"], 2)
        self.assertEqual(
            manifest["sources"][0]["sha256"], hashlib.sha256(first.read_bytes()).hexdigest()
        )
        self.assertEqual(manifest["sources"][1]["global_rows"], [3, 10])
        cross_file = manifest["assignments"][2]
        self.assertEqual(cross_file["profile_index"], 1)
        self.assertEqual(cross_file["load_index"], 0)
        self.assertEqual(cross_file["global_rows"], [2, 4])
        self.assertEqual(
            cross_file["source_segments"],
            [
                {"source_index": 0, "source_rows": [3, 3], "step_rows": [0, 1]},
                {"source_index": 1, "source_rows": [1, 1], "step_rows": [1, 2]},
            ],
        )
        self.assertEqual(
            manifest["unused_source_segments"],
            [
                {"source_index": 1, "source_rows": [6, 7]},
            ],
        )
        json.dumps(manifest, allow_nan=False)
        self.assertFalse(manifest["release_ready"])

    def test_packed_counts_do_not_claim_calendar_days(self):
        sources = [self.source(f"shape-{i}.csv", "1\n" * 8760) for i in range(4)]
        for count, paths, unused in ((68, sources[:3], 168), (91, sources, 96)):
            with self.subTest(load_count=count):
                result = pack_profiles(paths, load_count=count)
                self.assertEqual(len(result.profiles), 16)
                self.assertEqual(len(result.profiles[0]), count)
                self.assertEqual(len(result.profiles[0][0]), 24)
                self.assertEqual(result.manifest["unused_rows"], unused)
                self.assertFalse(result.manifest["calendar_provenance_verified"])

    def test_quoted_whitespace_and_negative_finite_numbers_are_preserved(self):
        source = self.source("finite.csv", '"1.5"\n -2.5 \n')
        result = pack_profiles([source], load_count=1, horizon=2)
        self.assertEqual(result.profiles, (((1.5, -2.5),),))

    def test_receipts_are_independent_and_raw_hashes_preserve_newline_bytes(self):
        first = self.source("lf.csv", "1\n2\n")
        second = self.root / "crlf.csv"
        second.write_bytes(b"1\r\n2\r\n")
        packed = pack_profiles([first], load_count=1, horizon=2)
        alternate = pack_profiles([second], load_count=1, horizon=2)
        self.assertEqual(packed.profiles, alternate.profiles)
        self.assertEqual(
            packed.manifest["packed_values_sha256"], alternate.manifest["packed_values_sha256"]
        )
        self.assertNotEqual(
            packed.manifest["sources"][0]["sha256"], alternate.manifest["sources"][0]["sha256"]
        )
        receipt = packed.manifest
        receipt["sources"][0]["sha256"] = "modified"
        self.assertNotEqual(packed.manifest["sources"][0]["sha256"], "modified")

    def test_rejects_bad_dimensions_and_unordered_or_single_path_inputs(self):
        source = self.source("one.csv", "1\n2\n")
        for kwargs in (
            {"load_count": 0},
            {"load_count": True},
            {"load_count": 1.0},
            {"load_count": 1, "horizon": 0},
            {"load_count": 1, "horizon": True},
            {"load_count": 1, "horizon": 2.0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                pack_profiles([source], **kwargs)
        for paths in ([], source, str(source), {source}, {"file": source}, iter([source]), [1]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                pack_profiles(paths, load_count=1, horizon=1)

    def test_rejects_duplicate_resolved_paths_and_missing_files(self):
        source = self.source("one.csv", "1\n2\n")
        alias = self.root / "alias.csv"
        alias.symlink_to(source)
        for paths in ([source, source], [source, alias], [self.root / "absent.csv"], [self.root]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                pack_profiles(paths, load_count=1, horizon=1)

    def test_rejects_malformed_empty_nonfinite_and_multiline_csv(self):
        for text in (
            "",
            "\n",
            "1\n\n2\n",
            "value\n",
            "1,2\n",
            "NaN\n",
            "inf\n",
            "-Infinity\n",
            "1e999\n",
            '"1\n2"\n',
            '"1\n',
            "1\n,\n",
        ):
            source = self.source("invalid.csv", text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                pack_profiles([source], load_count=1, horizon=1)
        binary = self.root / "binary.csv"
        binary.write_bytes(b"\xff\xfe")
        with self.assertRaises(ValueError):
            pack_profiles([binary], load_count=1, horizon=1)

    def test_rejects_insufficient_rows_and_preserves_sources(self):
        source = self.source("short.csv", "1\n2\n3\n")
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "complete profile"):
            pack_profiles([source], load_count=2, horizon=2)
        pack_profiles([source], load_count=1, horizon=2)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
