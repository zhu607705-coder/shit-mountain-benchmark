"""Current-review regressions, independent of upstream claimed results."""
import os
from pathlib import Path
import tempfile
import unittest
import baseline


class CacheBoundaryTests(unittest.TestCase):
    def test_invalid_utf8_text_operator_reports_build_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/"root";root.mkdir();(root/"binary").write_bytes(b"\xff")
            spec={"nodes":{"src":{"op":"source","path":"binary"},"out":{"op":"upper","deps":["src"]}}}
            with self.assertRaises(baseline.BuildError):
                baseline.Builder(root,Path(directory)/"cache").build(spec,"out")

    def test_relative_cache_location_survives_cwd_change(self):
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                root=Path(directory)/"root";root.mkdir();(root/"input").write_text("hello")
                spec={"nodes":{"src":{"op":"source","path":"input"},"out":{"op":"upper","deps":["src"]}}}
                builder=baseline.Builder(root,"cache")
                self.assertEqual(builder.build(spec,"out"),b"HELLO")
                Path("elsewhere").mkdir();os.chdir("elsewhere")
                self.assertEqual(builder.build(spec,"out"),b"HELLO")
            finally:
                os.chdir(previous)

    def test_corrupt_incomplete_cache_is_a_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/"root";root.mkdir();(root/"input").write_text("hello")
            cache=Path(directory)/"cache"
            spec={"nodes":{"src":{"op":"source","path":"input"},"out":{"op":"upper","deps":["src"]}}}
            baseline.Builder(root,cache).build(spec,"out")
            for file in cache.iterdir():
                if file.is_file(): file.write_bytes(b"\xff{broken")
            self.assertEqual(baseline.Builder(root,cache).build(spec,"out"),b"HELLO")


if __name__ == "__main__":
    unittest.main()
