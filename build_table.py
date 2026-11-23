#!/usr/bin/env python3
"""Validate reviews/*.json and write TABLE.md and docs/reviews.json (the data of the docs/ web page).

    python -I build_table.py            # validate, then write TABLE.md and docs/reviews.json
    python -I build_table.py --check    # validate only; exit 1 on a bad file (used by CI)
    python -I build_table.py --stale    # also ask `gh` which reviews are for an old head SHA (needs gh)

One file per PR (reviews/<pr>.json). Never edit TABLE.md by hand: it is generated.
Standard library only.
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
REVIEWS = ROOT / "reviews"
REPO = "ItsNotRexed/Leonida"

VERDICTS = ("in-progress", "do-not-merge", "notes", "clean", "scan-only", "not-reviewed")
# "clean" means: no malicious pattern found in the stated scope. It never means "safe".
REQUIRED = ("pr", "head_sha", "reviewer", "date", "scope", "verdict", "findings",
            "read_by_human", "commented_on_github")
ORDER = {v: i for i, v in enumerate(VERDICTS)}


DOUBLE_REQUIRED = ("reviewer", "verdict", "date", "head_sha", "scope", "findings")
MAX_DOUBLE_CHECKS = 10


def check_double_checks(name, value):
    """A review can carry second opinions on the same PR: `double_checks`, a list of
    {reviewer, verdict, date, head_sha, scope, findings[, read_by_human]}. The main review stays the one in the file."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_DOUBLE_CHECKS:
        return ["%s: double_checks must be a list of at most %d entries" % (name, MAX_DOUBLE_CHECKS)]
    problems = []
    for i, d in enumerate(value, 1):
        where = "%s: double_checks[%d]" % (name, i)
        if not isinstance(d, dict):
            problems.append("%s must be an object" % where)
            continue
        missing = [k for k in DOUBLE_REQUIRED if k not in d]
        if missing:
            problems.append("%s is missing %s" % (where, ", ".join(missing)))
            continue
        if d["verdict"] not in VERDICTS or d["verdict"] == "in-progress":
            problems.append("%s: verdict must be one of the finished verdicts" % where)
        if not all(isinstance(d[k], str) for k in ("reviewer", "date", "head_sha", "scope")):
            problems.append("%s: reviewer, date, head_sha and scope must be text" % where)
        if not isinstance(d["findings"], list) or not all(isinstance(x, str) for x in d["findings"]):
            problems.append("%s: findings must be a list of strings" % where)
        if "read_by_human" in d and not isinstance(d["read_by_human"], bool):
            problems.append("%s: read_by_human must be true or false" % where)
    return problems


def load():
    rows, errors = [], []
    # Layout: reviews/<verdict>/<pr>.json (clean, notes, do-not-merge, scan-only, not-reviewed, in-progress).
    # A flat reviews/<pr>.json is still read so an old claim is not lost, but the folder must match the verdict.
    paths = sorted(list(REVIEWS.glob("*.json")) + list(REVIEWS.glob("*/*.json")), key=lambda p: (len(p.stem), p.stem, str(p)))
    seen = {}
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors.append("%s: not readable JSON (%s)" % (path.name, e))
            continue
        # Automated scanner rows are visible only after a GitHub COMMENT has been confirmed.
        if data.get("source") == "leonida-security-monitor":
            auto_in_progress = (
                data.get("verdict") == "in-progress"
                and data.get("automatic_in_progress") is True
            )
            auto_scan_only = (
                data.get("verdict") == "scan-only"
                and data.get("reviewer") == "leonida-security-monitor/automated"
            )
            published_comment = (
                data.get("commented_on_github") is True
                and data.get("publication_status") == "published"
                and data.get("github_review_event") == "COMMENT"
            )
            if not (auto_in_progress or auto_scan_only or published_comment):
                continue
        missing = [k for k in REQUIRED if k not in data]
        if missing:
            errors.append("%s: missing %s" % (path.name, ", ".join(missing)))
            continue
        if not isinstance(data["pr"], int) or path.stem != str(data["pr"]):
            errors.append("%s: file name must be <pr>.json and match the pr field" % path.name)
        if data["verdict"] not in VERDICTS:
            errors.append("%s: verdict must be one of %s" % (path.name, ", ".join(VERDICTS)))
        folder = path.parent.name if path.parent != REVIEWS else None
        if folder is not None and data["verdict"] in VERDICTS and folder != data["verdict"]:
            errors.append("%s/%s: lives in folder %s but its verdict is %s" % (folder, path.name, folder, data["verdict"]))
        if data["pr"] in seen:
            errors.append("%s: PR %s already has a review in %s" % (path, data["pr"], seen[data["pr"]]))
        seen[data["pr"]] = str(path.relative_to(ROOT))
        if not isinstance(data["findings"], list) or not all(isinstance(x, str) for x in data["findings"]):
            errors.append("%s: findings must be a list of strings" % path.name)
        if not isinstance(data["read_by_human"], bool) or not isinstance(data["commented_on_github"], bool):
            errors.append("%s: read_by_human and commented_on_github must be true or false" % path.name)
        errors.extend(check_double_checks(path.name, data.get("double_checks")))
        rows.append(data)
    return rows, errors


def live_head(pr):
    try:
        out = subprocess.run(["gh", "pr", "view", str(pr), "-R", REPO, "--json", "headRefOid,state",
                              "-q", '.headRefOid + " " + .state'], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if out.returncode != 0 or " " not in out.stdout.strip():
        return None, None
    sha, state = out.stdout.strip().split(" ", 1)
    return sha, state


def cell(text):
    return str(text).replace("|", "/").replace("\n", " ").strip()


def render(rows, stale):
    rows = sorted(rows, key=lambda r: (ORDER.get(r["verdict"], 99), r["pr"]))
    counts = {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS}
    out = ["# Reviewed PRs", "",
           "Generated by `build_table.py` from `reviews/*.json`. Do not edit by hand.", "",
           "**Verdicts:** " + ", ".join("%s %d" % (v, counts[v]) for v in VERDICTS if counts[v]) + ".",
           "`clean` = no malicious pattern found in the stated scope. It is not a guarantee that a PR is safe.", "",
           "| PR | Verdict | Scope | Findings | Reviewer | Date | Human read | Commented | Head |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        flag = ""
        if r["pr"] in stale:
            flag = " ⚠ PR changed since this review"
        out.append("| [#%d](https://github.com/%s/pull/%d) | %s | %s | %s | %s | %s | %s | %s | `%s`%s |" % (
            r["pr"], REPO, r["pr"], r["verdict"], cell(r["scope"]),
            (cell("; ".join(r["findings"])) or "-") + "".join(
                " [double check by %s: %s]" % (cell(d["reviewer"]), cell(d["verdict"])) for d in r.get("double_checks") or []),
            cell(r["reviewer"]), r["date"],
            "yes" if r["read_by_human"] else "no", "yes" if r["commented_on_github"] else "no",
            cell(str(r["head_sha"])[:8]), flag))
    return "\n".join(out) + "\n"


def site_data(rows):
    """The same reviews as one JSON array for docs/index.html, newest PR first, one review per line.
    No timestamp, so the file only changes when a review does."""
    rows = sorted(rows, key=lambda r: -r["pr"])
    lines = []
    for r in rows:
        item = {"pr": r["pr"], "verdict": r["verdict"], "reviewer": str(r["reviewer"]), "date": str(r["date"]),
                "scope": str(r["scope"]), "findings": [str(f) for f in r["findings"]],
                "head": str(r["head_sha"])[:8], "human": r["read_by_human"], "commented": r["commented_on_github"],
                # A monitor that only matches patterns signs "<name>/automated": the page can set those apart.
                "automated": str(r["reviewer"]).endswith("/automated")}
        if r.get("double_checks"):
            item["double_checks"] = [{"reviewer": str(d["reviewer"]), "verdict": str(d["verdict"]), "date": str(d["date"]),
                                      "head": str(d["head_sha"])[:8], "scope": str(d["scope"]),
                                      "findings": [str(f) for f in d["findings"]], "human": bool(d.get("read_by_human", False))}
                                     for d in r["double_checks"]]
        for key, field in (("title", "pr_title"), ("author", "author")):   # optional, written by some agents
            if isinstance(r.get(field), str) and r[field].strip():
                item[key] = r[field].strip()[:200]
        lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
    return "[\n" + ",\n".join(lines) + "\n]\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stale", action="store_true")
    args = ap.parse_args()
    rows, errors = load()
    if errors:
        for e in errors:
            print("error:", e, file=sys.stderr)
        return 1
    stale = set()
    if args.stale:
        for r in rows:
            sha, _ = live_head(r["pr"])
            if sha and not str(sha).startswith(str(r["head_sha"])[:8]) and r["head_sha"] != "unknown":
                stale.add(r["pr"])
        print("stale reviews:", sorted(stale) or "none")
    if args.check:
        print("%d reviews OK" % len(rows))
        return 0
    (ROOT / "TABLE.md").write_text(render(rows, stale), encoding="utf-8", newline="\n")
    print("TABLE.md written (%d reviews)" % len(rows))
    if not stale:   # the site file is committed by CI: keep it free of what only a --stale run knows
        (ROOT / "docs").mkdir(exist_ok=True)
        (ROOT / "docs" / "reviews.json").write_text(site_data(rows), encoding="utf-8", newline="\n")
        print("docs/reviews.json written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
