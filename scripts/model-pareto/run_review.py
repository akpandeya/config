#!/usr/bin/env python3
"""Reviewer arm: a real PR diff with planted bugs is staged in a clone; each model reviews it.

Usage: run_review.py --task TASK.json --out RUNS_DIR --models "p/A,p/B" [--harness pi] [--tag review1]
The task manifest needs a "review" key: {"bugs": [{"id", "file", "old", "new", "pattern"}]} where old/new
is the planted edit and pattern is a regex a finding must match to count as detecting that bug.
Recall is scored automatically from the reply; false positives are judged by hand from reply.md.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_cell  # noqa: E402

PROMPT = """You are reviewing a staged change in this repository (run `git diff --cached` to see it).
Find correctness bugs: wrong behaviour against the intended feature, logic errors, off-by-one errors,
swallowed failures. Do NOT modify any files. Read surrounding code as needed.
Finish with a numbered list; each item: file:line, severity (high/medium/low), what is wrong and why.
Only report real defects, not style preferences."""


def build_tree(task, work):
    subprocess.run(["git", "clone", "-q", "--no-checkout", task["repo"], work], check=True)
    subprocess.run(["git", "-C", work, "checkout", "-q", task["base"]], check=True)
    subprocess.run(["git", "-C", work, "remote", "remove", "origin"], check=True)
    patch = subprocess.run(["git", "-C", task["repo"], "diff", task["base"], task["solution"]],
                           capture_output=True, check=True).stdout
    subprocess.run(["git", "-C", work, "apply"], input=patch, check=True)
    for bug in task["review"]["bugs"]:
        path = os.path.join(work, bug["file"])
        with open(path) as fh:
            text = fh.read()
        if bug["old"] not in text:
            sys.exit("planted-bug anchor missing: " + bug["id"])
        with open(path, "w") as fh:
            fh.write(text.replace(bug["old"], bug["new"], 1))
    subprocess.run(["git", "-C", work, "add", "-A"], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--harness", default="pi")
    parser.add_argument("--tag", default="review1")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    with open(args.task) as fh:
        task = json.load(fh)

    def run(model):
        run_dir = os.path.join(args.out, "%s-%s-%s" % (args.tag, re.sub(r"[^a-z0-9]+", "-", model.split("/")[-1].lower()).strip("-"), args.harness))
        if os.path.exists(os.path.join(run_dir, "result.json")):
            return
        os.makedirs(run_dir, exist_ok=True)
        work = os.path.join(run_dir, "work")
        build_tree(task, work)
        prices = run_cell.load_prices(model)
        if args.harness == "pi":
            command = ["pi", "-p", "--no-session", "--mode", "json", "--model", model, PROMPT]
        else:
            command = ["opencode", "run", "-m", model, "--agent", "coder", "--auto", "--format", "json", PROMPT]
        events = os.path.join(run_dir, "events.jsonl")
        started = time.time()
        with open(events, "w") as out, open(os.path.join(run_dir, "stderr.log"), "w") as err:
            try:
                subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                               timeout=args.timeout, env=dict(os.environ, PWD=work))
            except subprocess.TimeoutExpired:
                pass
        wall = round(time.time() - started, 1)
        tokens, reported, tool_calls, turns, final_text = run_cell.parse_events(args.harness, events)
        modified = subprocess.run(["git", "-C", work, "status", "--porcelain"], capture_output=True, text=True).stdout
        with open(os.path.join(run_dir, "reply.md"), "w") as fh:
            fh.write(final_text)
        detected = {b["id"]: bool(re.search(b["pattern"], final_text, re.S | re.I)) for b in task["review"]["bugs"]}
        result = {"model": model, "harness": args.harness, "wall_seconds": wall, "tokens": tokens,
                  "cost_catalog_usd": round(run_cell.price(tokens, prices), 4), "turns": turns,
                  "tool_calls": tool_calls, "detected": detected,
                  "recall": "%d/%d" % (sum(detected.values()), len(detected)),
                  "modified_files": [l for l in modified.splitlines() if not l.startswith(("A ", "AM"))][:5]}
        with open(os.path.join(run_dir, "result.json"), "w") as fh:
            json.dump(result, fh, indent=1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, [m for m in args.models.split(",") if m]))


if __name__ == "__main__":
    main()
