import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import build_ui


class UIBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "icons").mkdir()
        self.write("index.html", '<!doctype html>\r\n<html><head><title>抽一道</title></head><body></body></html>\r\n')
        self.write("app.js", 'console.log("ready");\n')
        self.write("style.css", "body { color: white; }\n")
        self.write("icons/play.svg", '<svg viewBox="0 0 24 24"></svg>\n')
        self.registry = self.root / "benchmark.json"
        self.registry.write_text('{"version":"0.2.1"}', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, value):
        path = self.web / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode("utf-8"))

    def snapshot(self):
        return {path.relative_to(self.web).as_posix(): path.read_bytes() for path in self.web.rglob("*") if path.is_file()}

    def test_repeated_build_is_stable_and_check_does_not_write(self):
        first = build_ui.build(self.web, "0.2.1")
        snapshot = self.snapshot()
        second = build_ui.build(self.web, "0.2.1")
        self.assertEqual(first, second)
        self.assertEqual(first, build_ui.build(self.web, "0.2.1", check=True))
        self.assertEqual(snapshot, self.snapshot())
        self.assertEqual(json.loads((self.web / "build.txt").read_bytes()), first)
        self.assertIn(f'content="{first["id"]}"'.encode(), snapshot["index.html"])
        self.assertIn(b"\r\n", snapshot["index.html"])

    def test_each_browser_asset_change_invalidates_stamp_and_manifest(self):
        previous = build_ui.build(self.web, "0.2.1")
        for asset in ("app.js", "style.css", "icons/play.svg", "index.html"):
            with self.subTest(asset=asset):
                with (self.web / asset).open("ab") as output:
                    output.write(b"\n")
                before_check = self.snapshot()
                with self.assertRaisesRegex(ValueError, "changed"):
                    build_ui.build(self.web, "0.2.1", check=True)
                self.assertEqual(before_check, self.snapshot())
                current = build_ui.build(self.web, "0.2.1")
                self.assertNotEqual(previous["id"], current["id"])
                previous = current

    def test_stamp_value_is_normalized_but_mismatch_is_rejected(self):
        first = build_ui.build(self.web, "0.2.1")
        original = (self.web / "index.html").read_bytes().decode("utf-8")
        self.write("index.html", original.replace(first["id"], "stale-tab-build"))
        self.assertEqual(build_ui.compute_manifest(self.web, "0.2.1"), first)
        with self.assertRaisesRegex(ValueError, "changed"):
            build_ui.build(self.web, "0.2.1", check=True)
        self.assertEqual(build_ui.build(self.web, "0.2.1"), first)
        self.assertEqual(build_ui.build(self.web, "0.2.1", check=True), first)

    def test_manifest_covers_exact_assets_and_excludes_tests_docs_and_itself(self):
        self.write("test_widget.js", "test only")
        self.write("widget.test.js", "test only")
        self.write("tests/browser.js", "test only")
        self.write("README.md", "documentation")
        self.write("icons/SOURCE.json", "{}")
        self.write("build.txt", "stale manifest")
        first = build_ui.build(self.web, "0.2.1")
        self.assertEqual(set(first["assets"]), {"index.html", "app.js", "style.css", "icons/play.svg"})
        self.assertEqual(first["assets"]["app.js"], hashlib.sha256((self.web / "app.js").read_bytes()).hexdigest())
        self.write("README.md", "different documentation")
        self.assertEqual(build_ui.build(self.web, "0.2.1", check=True), first)
        self.write("freshness.js", "new browser resource")
        with self.assertRaises(ValueError):
            build_ui.build(self.web, "0.2.1", check=True)
        self.assertNotEqual(first["id"], build_ui.build(self.web, "0.2.1")["id"])

    def test_version_change_changes_build_identity(self):
        previous = build_ui.build(self.web, "0.2.1")
        with self.assertRaises(ValueError):
            build_ui.build(self.web, "0.2.2", check=True)
        current = build_ui.build(self.web, "0.2.2")
        self.assertNotEqual(previous["id"], current["id"])
        self.assertEqual(current["version"], "0.2.2")
        self.assertEqual(current["schema"], 1)

    def test_existing_meta_preserves_all_but_content(self):
        source = "<HTML><HEAD><META data-extra='keep' CONTENT='old' NAME='arena-ui-build'></HEAD></HTML>"
        self.assertEqual(build_ui.stamp_index(source, "new"), source.replace("CONTENT='old'", "CONTENT='new'"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_ui.stamp_index(source.replace("</HEAD>", '<meta name="arena-ui-build" content="other"></HEAD>'), "new")

    def test_cli_failure_then_build_then_check(self):
        command = [sys.executable, str(Path(build_ui.__file__)), "--web-root", str(self.web), "--registry", str(self.registry)]
        before = self.snapshot()
        failed = subprocess.run([*command, "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(self.snapshot(), before)
        built = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(built.returncode, 0, built.stderr)
        checked = subprocess.run([*command, "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(built.stdout)["id"], json.loads(checked.stdout)["id"])


if __name__ == "__main__":
    unittest.main()
