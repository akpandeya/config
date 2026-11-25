#!/usr/bin/env python3
"""Score a planner run: recall of the real change's production files in PLAN.md, and file names it invented.

Usage: score_plan.py --task TASK.json --run RUN_DIR
Writes RUN_DIR/plan_score.json. Matching is by file basename (without extension), case-insensitive.
"""
import argparse
import json
import os
import re
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    task = json.load(open(args.task))
    gold = subprocess.run(["git", "-C", task["repo"], "diff", "--name-only", task["base"], task["solution"], "--",
                           "src/main"], capture_output=True, text=True, check=True).stdout.split()
    plan_path = os.path.join(args.run, "work", "PLAN.md")
    plan = open(plan_path).read() if os.path.exists(plan_path) else ""
    lowered = plan.lower()
    names = {os.path.splitext(os.path.basename(p))[0].lower(): p for p in gold}
    hit = [p for n, p in names.items() if n in lowered]
    mentioned = set(re.findall(r"[\w./-]+\.(?:kt|sql)\b", plan))
    work = os.path.join(args.run, "work")
    invented = sorted(m for m in mentioned if not any(
        os.path.exists(os.path.join(work, m)) or m.endswith(os.path.basename(g)) for g in gold)
        and not subprocess.run(["git", "-C", work, "ls-files", "--", "*" + os.path.basename(m)],
                               capture_output=True, text=True).stdout.strip())
    score = {"plan_exists": bool(plan), "plan_chars": len(plan), "gold_files": len(gold), "gold_hit": len(hit),
             "recall": round(len(hit) / len(gold), 2) if gold else None, "missed": sorted(set(gold) - set(hit)),
             "unknown_files_named": invented, "mentions_two_commits": bool(re.search(r"commit (2|two)", lowered))}
    json.dump(score, open(os.path.join(args.run, "plan_score.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in score.items() if k != "missed"}))


if __name__ == "__main__":
    main()
