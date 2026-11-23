#!/usr/bin/env python3
"""Write docs/coverage.json: how much of Leonida's open pull request queue has a review on record, and which
reviews are out of date because the pull request got a new commit after it was read.

    python -I scripts/coverage.py                 # list the open PRs with gh, then write docs/coverage.json
    python -I scripts/coverage.py --open-file F   # read "number [head sha]" lines from F instead: tests, offline

Run by the table workflow on its schedule, not on every push: listing about 4,500 open PRs is about 45 API calls.
It only reads: the open PR numbers and head commits of ItsNotRexed/Leonida, and this repository's own review files. Standard library
only; needs gh and GH_TOKEN unless --open-file is given. If the listing fails, nothing is written and the old file
stays, so the page keeps the last known numbers and their time.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_table  # noqa: E402

REPO = "ItsNotRexed/Leonida"
NEWEST = 30          # how many unreviewed PR numbers the page lists as free to take


def open_heads_from_gh():
    out = subprocess.run(["gh", "api", "--paginate", "repos/%s/pulls?state=open&per_page=100" % REPO,
                          "--jq", r'.[] | "\(.number) \(.head.sha)"'], capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError("gh could not list the open pull requests: %s" % out.stderr.strip()[:300])
    return parse_heads(out.stdout)


def parse_heads(text):
    """Lines of "number" or "number sha" -> {number: sha or ""}. Anything else is ignored."""
    heads = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit():
            sha = parts[1].lower() if len(parts) > 1 and all(c in "0123456789abcdef" for c in parts[1].lower()) else ""
            heads[int(parts[0])] = sha
    return heads


def is_stale(reviewed_sha, live_sha):
    """True when both commits are known and the PR's head is no longer the one that was reviewed.
    Review files hold 7 to 40 hex characters, so compare on the shorter length. Unknown means: cannot tell."""
    reviewed_sha, live_sha = str(reviewed_sha or "").lower(), str(live_sha or "").lower()
    if len(reviewed_sha) < 7 or not live_sha or any(c not in "0123456789abcdef" for c in reviewed_sha):
        return False
    return not live_sha.startswith(reviewed_sha[:40])


def summarize(open_heads, rows, as_of):
    """open_heads: {open PR number: head sha or ""} (a plain set of numbers also works: nothing is stale then).
    rows: the reviews build_table.load() returns. Every count is about PRs that are open right now."""
    if not isinstance(open_heads, dict):
        open_heads = {n: "" for n in open_heads}
    open_numbers = set(open_heads)
    verdict = {r["pr"]: r["verdict"] for r in rows}
    stale = sorted((r["pr"] for r in rows if r["pr"] in open_heads and r["verdict"] != "in-progress"
                    and is_stale(r.get("head_sha"), open_heads[r["pr"]])), reverse=True)
    in_progress = {n for n in open_numbers if verdict.get(n) == "in-progress"}
    scan_only = {n for n in open_numbers if verdict.get(n) == "scan-only"}
    reviewed = {n for n in open_numbers if n in verdict} - in_progress
    unreviewed = sorted(open_numbers - reviewed - in_progress, reverse=True)
    return {"as_of": as_of, "open_total": len(open_numbers), "reviewed_open": len(reviewed),
            "scan_only_open": len(scan_only), "in_progress_open": len(in_progress),
            "unreviewed_total": len(unreviewed), "newest_unreviewed": unreviewed[:NEWEST],
            # reviews whose PR got a new commit since: the verdict is about code that is no longer the PR's head
            "stale_total": len(stale), "stale": stale}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-file")
    args = ap.parse_args()
    rows, errors = build_table.load()
    if errors:
        for e in errors:
            print("error:", e, file=sys.stderr)
        return 1
    try:
        numbers = (parse_heads(pathlib.Path(args.open_file).read_text(encoding="utf-8")) if args.open_file
                   else open_heads_from_gh())
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        print("coverage not updated:", e, file=sys.stderr)
        return 0
    if not numbers:
        print("coverage not updated: the open pull request list came back empty", file=sys.stderr)
        return 0
    as_of = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = summarize(numbers, rows, as_of)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "coverage.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("docs/coverage.json written: %d open, %d reviewed, %d unreviewed, %d out of date" % (
        data["open_total"], data["reviewed_open"], data["unreviewed_total"], data["stale_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
