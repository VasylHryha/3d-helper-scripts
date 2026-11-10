import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers3d import blender, config, provenance


class FindBlenderTests(unittest.TestCase):
    def test_newest_install_wins_on_each_platform(self):
        cases = {
            "darwin": ["/Applications/Blender 4.2.app/Contents/MacOS/Blender",
                       "/Applications/Blender 5.2.app/Contents/MacOS/Blender"],
            "win32": [r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
                      r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"],
            "linux": ["/opt/blender-4.2/blender", "/opt/blender-5.2/blender"],
        }
        for platform, installs in cases.items():
            found = blender.find_blender(platform=platform, env={}, home="/h", which=lambda name: None,
                                         glob=lambda pattern, installs=installs: installs[:] if "Blender" in pattern
                                         or "blender" in pattern else [])
            self.assertIn("5.2", found, platform)

    def test_path_and_explicit_override(self):
        self.assertEqual(blender.find_blender(env={}, which=lambda n: "/x/blender", glob=lambda p: []), "/x/blender")
        with tempfile.NamedTemporaryFile() as fake:
            self.assertEqual(blender.find_blender(env={"BLENDER_BIN": fake.name}, which=lambda n: "/x/blender"),
                             fake.name)
        with self.assertRaises(FileNotFoundError):
            blender.find_blender(env={"BLENDER_BIN": "/missing"}, which=lambda n: "/x/blender")

    def test_nothing_found(self):
        self.assertIsNone(blender.find_blender(platform="linux", env={}, home="/h", which=lambda n: None,
                                               glob=lambda p: []))


class ConfigTests(unittest.TestCase):
    def test_env_key_beats_config_file_and_home_is_overridable(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "config.json").write_text(json.dumps({"tripo_api_key": "from-file"}))
            with mock.patch.dict(os.environ, {"H3D_HOME": folder}, clear=False):
                os.environ.pop("TRIPO_API_KEY", None)
                self.assertEqual(config.tripo_key(), "from-file")
                os.environ["TRIPO_API_KEY"] = "from-env"
                self.assertEqual(config.tripo_key(), "from-env")
                self.assertEqual(config.credit_log_path(), Path(folder) / "credits.jsonl")


class ProvenanceTests(unittest.TestCase):
    def test_changed_file_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            asset = Path(folder) / "m.glb"
            asset.write_bytes(b"one")
            self.assertEqual(provenance.verify_record(asset), "missing")
            provenance.write_record(asset, "somewhere", "tool", "CC0")
            self.assertEqual(provenance.verify_record(asset), "ok")
            asset.write_bytes(b"two")
            self.assertEqual(provenance.verify_record(asset), "changed")

    def test_converted_file_keeps_licence_and_links_source_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            source, derived = Path(folder) / "a.glb", Path(folder) / "b.fbx"
            source.write_bytes(b"src")
            derived.write_bytes(b"out")
            provenance.write_record(source, "Tripo API", "3d-helper-scripts", "my licence", task_id="t1")
            record = json.loads(provenance.write_derived_record(source, derived, "convert").read_text())
            self.assertEqual((record["license"], record["task_id"]), ("my licence", "t1"))
            self.assertEqual(record["derived_from"], {"file": "a.glb", "sha256": provenance.sha256_of(source)})


if __name__ == "__main__":
    unittest.main()
