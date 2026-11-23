"""Offline tests for the optional `double_checks` field of a review (second opinions on a PR already reviewed)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_table as bt  # noqa: E402


def entry(**kw):
    d = {"reviewer": "bob/claude", "verdict": "clean", "date": "2026-11-23", "head_sha": "abcdef12",
         "scope": "static, diff only", "findings": ["read the diff"], "read_by_human": False}
    d.update(kw)
    return d


class DoubleChecks(unittest.TestCase):
    def test_absent_or_empty_is_fine(self):
        self.assertEqual(bt.check_double_checks("1.json", None), [])
        self.assertEqual(bt.check_double_checks("1.json", []), [])

    def test_a_good_entry_passes(self):
        self.assertEqual(bt.check_double_checks("1.json", [entry(), entry(reviewer="eve/claude", verdict="notes")]), [])

    def test_bad_shapes_are_reported(self):
        for bad in ("text", {"a": 1}, [entry()] * 11, ["not an object"], [entry(verdict="safe")],
                    [entry(verdict="in-progress")], [entry(findings="x")], [entry(findings=[1])],
                    [entry(reviewer=5)], [entry(read_by_human="yes")], [{"reviewer": "x"}]):
            self.assertTrue(bt.check_double_checks("1.json", bad), repr(bad))

    def test_table_and_site_show_the_double_check(self):
        row = {"pr": 7, "head_sha": "abcdef12", "reviewer": "alice/claude", "date": "2026-11-23", "scope": "s", "verdict": "clean",
               "findings": ["f"], "read_by_human": False, "commented_on_github": False, "double_checks": [entry()]}
        self.assertIn("double check by bob/claude: clean", bt.render([row], set()))
        site = bt.site_data([row])
        self.assertIn('"double_checks"', site)
        self.assertIn("bob/claude", site)
        plain = dict(row)
        del plain["double_checks"]
        self.assertNotIn("double_checks", bt.site_data([plain]))


if __name__ == "__main__":
    unittest.main()
