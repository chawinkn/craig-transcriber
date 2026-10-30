import sys
import tempfile
import unittest
from pathlib import Path


class HistoryCommentsTest(unittest.TestCase):
    def found(self, name, text):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        self.addCleanup(sys.path.pop, 0)
        import no_history_comments

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / name
        path.write_text(text, encoding="utf-8")
        return list(no_history_comments.find([str(path)]))

    def test_flags_history_in_comments(self):
        self.assertEqual(len(self.found("a.py", "x = 1  # fixed in #12\n# used to be slow\n# on 2026-10-29\n")), 3)
        self.assertEqual(len(self.found("a.js", "f() // previously a loop\n/* the reviewer\nwanted it */\n")), 2)
        self.assertEqual(len(self.found("a.css", "/* measured on a laptop */ a { color: red }\n")), 1)

    def test_ignores_code_strings_and_plain_comments(self):
        self.assertEqual(self.found("a.py", 'x = "used to #12 2026-10-29"  # noqa: E501\n'), [])
        self.assertEqual(self.found("a.js", "const s = '// previously'; // colour #fff\n"), [])
        self.assertEqual(self.found("a.css", "a { color: #123456 } /* why this works */\n"), [])


if __name__ == "__main__":
    unittest.main()
