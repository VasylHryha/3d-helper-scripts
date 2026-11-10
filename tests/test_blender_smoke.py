"""Runs real headless Blender when it is installed; skipped otherwise."""
import json
import tempfile
import unittest
from pathlib import Path

from helpers3d import blender

CUBE_OBJ = """o cube
v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 4 3 2
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""


@unittest.skipUnless(blender.find_blender(), "Blender not installed")
class BlenderSmokeTests(unittest.TestCase):
    def run_builtin(self, name, args):
        return blender.run_script(blender.scripts_dir() / name, args, timeout=300)

    def test_check_convert_views_and_sheet(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cube = root / "cube.obj"
            cube.write_text(CUBE_OBJ)

            report_path = root / "report.json"
            self.assertEqual(self.run_builtin("mesh_check.py", ["--model", str(cube), "--json", str(report_path)]), 0)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["triangles"], 12)
            self.assertEqual(report["size_xyz"], [2.0, 2.0, 2.0])
            self.assertEqual(report["open_edges"], 0)

            glb = root / "cube.glb"
            self.assertEqual(self.run_builtin("convert.py", ["--model", str(cube), "--out", str(glb),
                                                             "--height", "4", "--ground"]), 0)
            self.assertTrue(glb.is_file())

            views = root / "views"
            self.assertEqual(self.run_builtin("views.py", ["--model", str(glb), "--out", str(views), "--size", "64"]), 0)
            self.assertTrue((views / "views_sheet.png").is_file())
            self.assertTrue((views / "front.png").is_file())

            sheet = root / "sheet.png"
            self.assertEqual(self.run_builtin("sheet.py", ["--out", str(sheet), "--cell", "32", "--images",
                                                           str(views / "front.png"), str(views / "back.png")]), 0)
            self.assertTrue(sheet.is_file())


if __name__ == "__main__":
    unittest.main()
