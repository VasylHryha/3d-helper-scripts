import unittest

from helpers3d import scan


class ScanTests(unittest.TestCase):
    def test_finds_key_private_path_and_deny_term(self):
        text = "\n".join([
            'key = "' + "tsk" + '_abcdefghijklmnopqrstuvwx"',
            "open('/" + "Users/someone/file')",
            "this mentions SecretGame here",
            "all fine",
        ])
        findings = scan.scan_text("a.py", text, terms=["secretgame"])
        self.assertEqual([(f.line, f.what.split()[0]) for f in findings], [(1, "Tripo"), (2, "macOS/Linux"), (3, "deny-term")])

    def test_clean_text_has_no_findings(self):
        self.assertEqual(scan.scan_text("a.py", "TRIPO_API_KEY=your_key_here\npath = '~/models'", []), [])


if __name__ == "__main__":
    unittest.main()
