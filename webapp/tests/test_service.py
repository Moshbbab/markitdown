from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import service


class FakeConverter:
    def convert_local(self, path: str | Path):
        source = Path(path)
        if source.name.startswith("bad"):
            raise RuntimeError("conversion failed")
        return SimpleNamespace(markdown=f"# {source.stem}\n\nConverted")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_file(self, name: str, content: str = "test") -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    @patch.dict(service.os.environ, {"MAX_FILE_MB": "1", "MAX_TOTAL_MB": "2"})
    def test_single_file_returns_markdown(self):
        source = self.make_file("report.txt")
        records, output = service.convert_paths(
            [source], converter_factory=FakeConverter
        )
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].success)
        self.assertIsNotNone(output)
        self.assertEqual(Path(output).suffix, ".md")
        self.assertIn("# report", Path(output).read_text(encoding="utf-8"))

    def test_batch_continues_after_failure_and_returns_zip(self):
        good = self.make_file("good.txt")
        bad = self.make_file("bad.txt")
        records, output = service.convert_paths(
            [good, bad], converter_factory=FakeConverter
        )
        self.assertEqual([record.success for record in records], [True, False])
        self.assertIsNotNone(output)
        self.assertEqual(Path(output).suffix, ".zip")
        with zipfile.ZipFile(output) as archive:
            self.assertIn("good.md", archive.namelist())
            self.assertIn("conversion-report.md", archive.namelist())

    def test_rejects_unknown_extension(self):
        source = self.make_file("payload.exe")
        with self.assertRaisesRegex(ValueError, "صيغة غير مدعومة"):
            service.convert_paths([source], converter_factory=FakeConverter)

    def test_duplicate_stems_get_unique_output_names(self):
        first_dir = self.root / "a"
        second_dir = self.root / "b"
        first_dir.mkdir()
        second_dir.mkdir()
        first = first_dir / "report.txt"
        second = second_dir / "report.txt"
        first.write_text("one", encoding="utf-8")
        second.write_text("two", encoding="utf-8")

        records, output = service.convert_paths(
            [first, second], converter_factory=FakeConverter
        )
        self.assertEqual(
            [record.output_name for record in records],
            ["report.md", "report-2.md"],
        )
        self.assertEqual(Path(output).suffix, ".zip")


if __name__ == "__main__":
    unittest.main()
