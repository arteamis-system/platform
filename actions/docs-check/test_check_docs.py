"""Exercise rejection paths as well as a valid documentation repository."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CHECKER = Path(__file__).with_name("check_docs.py")


class DocsCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write(".docscheck.json", json.dumps({
            "required": ["title", "status", "owner", "last_reviewed"],
            "statuses": ["accepted"], "indexed": True,
            "decisions": {"dir": "decisions", "id_prefix": "PDR-", "required": ["id"]},
            "requirement_index": {"file": "README.md", "id_pattern": r"F-\d+[a-z]?",
                                  "statuses": ["Built", "Implemented"]},
        }))
        self.write("README.md", "[Guide](guide.md)\n\n| ID | Status |\n|---|---|\n| F-1 | Built |\n| F-2a | Implemented |\n")
        self.write("guide.md", "---\ntitle: Guide\nstatus: accepted\nowner: Team\nlast_reviewed: 2026-10-14\n---\n\nGuide.\n")

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_checker(self):
        return subprocess.run([sys.executable, str(CHECKER), str(self.root)],
                              capture_output=True, text=True)

    def assert_rejected(self, expected):
        result = self.run_checker()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(expected, result.stdout)

    def test_valid_repository(self):
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_broken_link(self):
        self.write("README.md", (self.root / "README.md").read_text() + "[Missing](missing.md)\n")
        self.assert_rejected("broken link: missing.md")

    def test_duplicate_requirement_with_letter_suffix(self):
        self.write("README.md", (self.root / "README.md").read_text() + "| F-2a | Built |\n")
        self.assert_rejected("requirement F-2a is listed twice")

    def test_unknown_requirement_status(self):
        self.write("README.md", (self.root / "README.md").read_text().replace("Implemented", "Live"))
        self.assert_rejected("unknown status 'Live'")

    def test_overescaped_requirement_pattern(self):
        path = self.root / ".docscheck.json"
        config = json.loads(path.read_text())
        config["requirement_index"]["id_pattern"] = r"F-\\d+"
        path.write_text(json.dumps(config))
        self.assert_rejected("no matching requirement ids")

    def test_invalid_calendar_date(self):
        self.write("guide.md", (self.root / "guide.md").read_text().replace("2026-10-14", "2026-02-30"))
        self.assert_rejected("valid YYYY-MM-DD")

    def test_missing_index_entry(self):
        self.write("other.md", (self.root / "guide.md").read_text())
        self.assert_rejected("not linked from any README.md index")

    def test_decision_id_must_match_filename(self):
        self.write("decisions/0001-example.md", (self.root / "guide.md").read_text().replace("title:", "id: PDR-0002\ntitle:"))
        self.assert_rejected("decision id must be PDR-0001")


if __name__ == "__main__":
    unittest.main()
