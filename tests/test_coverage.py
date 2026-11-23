"""Offline tests for scripts/coverage.py: no network, no gh. Run: python -I -m unittest discover -s tests"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coverage  # noqa: E402


def row(pr, verdict, head_sha="unknown"):
    return {"pr": pr, "verdict": verdict, "head_sha": head_sha}


class Summarize(unittest.TestCase):
    def test_counts_only_open_prs(self):
        rows = [row(1, "clean"), row(2, "notes"), row(3, "in-progress"), row(4, "scan-only"), row(99, "clean")]
        got = coverage.summarize({1, 2, 3, 4, 5, 6}, rows, "T")
        self.assertEqual(got["open_total"], 6)
        self.assertEqual(got["reviewed_open"], 3)        # 1, 2 and 4: PR 99 is reviewed but no longer open
        self.assertEqual(got["scan_only_open"], 1)
        self.assertEqual(got["in_progress_open"], 1)
        self.assertEqual(got["unreviewed_total"], 2)
        self.assertEqual(got["newest_unreviewed"], [6, 5])
        self.assertEqual(got["as_of"], "T")

    def test_the_parts_add_up(self):
        rows = [row(n, "clean") for n in range(1, 40, 3)] + [row(50, "in-progress")]
        got = coverage.summarize(set(range(1, 101)), rows, "T")
        self.assertEqual(got["reviewed_open"] + got["in_progress_open"] + got["unreviewed_total"], got["open_total"])

    def test_newest_unreviewed_is_capped_and_newest_first(self):
        got = coverage.summarize(set(range(1, 501)), [], "T")
        self.assertEqual(len(got["newest_unreviewed"]), coverage.NEWEST)
        self.assertEqual(got["newest_unreviewed"][0], 500)
        self.assertEqual(got["unreviewed_total"], 500)

    def test_parse_heads_ignores_noise(self):
        got = coverage.parse_heads("12 ABCDEF1234\n7\n\nnot-a-number\n9 zzz\n")
        self.assertEqual(got, {12: "abcdef1234", 7: "", 9: ""})


A = "a" * 40
B = "b" * 40


class Stale(unittest.TestCase):
    def test_same_commit_is_not_stale_even_when_the_review_holds_a_short_sha(self):
        self.assertFalse(coverage.is_stale(A, A))
        self.assertFalse(coverage.is_stale(A[:8], A))

    def test_new_commit_is_stale(self):
        self.assertTrue(coverage.is_stale(A, B))
        self.assertTrue(coverage.is_stale(A[:8], B))

    def test_unknown_on_either_side_is_never_called_stale(self):
        for reviewed, live in (("unknown", B), ("", B), (A, ""), ("abc", B), ("not-hex!", B)):
            self.assertFalse(coverage.is_stale(reviewed, live), (reviewed, live))

    def test_summarize_lists_stale_reviews_of_open_prs_only(self):
        rows = [row(1, "clean", A), row(2, "clean", A), row(3, "notes", A[:8]), row(4, "in-progress", A),
                row(5, "clean", "unknown"), row(99, "clean", A)]
        got = coverage.summarize({1: A, 2: B, 3: B, 4: B, 5: B, 6: B}, rows, "T")
        self.assertEqual(got["stale"], [3, 2])          # 4 is only a claim, 5 is unknown, 99 is not open
        self.assertEqual(got["stale_total"], 2)
        self.assertEqual(got["reviewed_open"], 4)       # a stale review still counts as a review on record

    def test_a_set_of_numbers_still_works_and_nothing_is_stale(self):
        got = coverage.summarize({1, 2}, [row(1, "clean", A)], "T")
        self.assertEqual((got["open_total"], got["stale_total"]), (2, 0))


if __name__ == "__main__":
    unittest.main()
