#!/usr/bin/env python3
"""Blind, shuffled quality review of finished cells by an independent reviewer model.

Usage: run_blind_review.py --task TASK.json --ticket TICKET.md --key KEY.md --out DIR
                           --model "provider/Model" --runs RUN_DIR [RUN_DIR ...] [--gold] [--workers 3]

Each cell's final diff (solution.patch) is copied to DIR/blind/cell-NN/ under an anonymous,
shuffled label, together with the ticket and the answer key. The reviewer runs on OpenCode in
a directory that holds only those files, so it sees no model, harness or cost. It writes a JSON
rubric. DIR/mapping.json (label -> run dir) is only read when results are un-blinded.
--gold adds the real merged change as one more anonymous cell, as a calibration point.
"""
import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_cell import load_prices, parse_events, price  # noqa: E402

RUBRIC = ["spec_quality", "behaviour_vs_ticket", "scope_discipline", "test_quality", "code_quality"]

PROMPT = """You are an independent senior reviewer. Review ONE implementation of a Jira ticket in a Kotlin/Spring service.
Files in this directory (read them with your tools; do not edit anything):
- ticket.md : the ticket as the developer wrote it
- key.md : facts the developer knows about the intended behaviour (what a correct result must do)
- change.patch : the complete diff produced by an unknown author (new spec docs under specs/, production code, tests, migrations)

Score each criterion 0-5 (5 = excellent, 3 = acceptable, 0 = absent or wrong), with one or two sentences of evidence
citing file names from change.patch:
- spec_quality: does the added spec/plan/tasks document match the ticket and key, cover the edge cases, stay readable?
- behaviour_vs_ticket: does the code implement the behaviour in ticket.md and key.md (read-only effective date, undo,
  validation rules, status, charts reading the effective date)? List behaviours missing or wrong.
- scope_discipline: are changes outside what the ticket needs justified? Flag unrelated edits, renames, or new config.
- test_quality: do tests assert distinguishing, non-default values; do they cover validation and undo; any tautologies?
- code_quality: layering, naming, error handling, migration safety, concurrency or data-integrity risks.
Also list the top 3 defects a human reviewer would block the PR on.
Finish your reply with ONE line of JSON and nothing after it:
RESULT_JSON: {"spec_quality": n, "behaviour_vs_ticket": n, "scope_discipline": n, "test_quality": n, "code_quality": n, "blockers": ["...", "...", "..."]}
"""


def review(cell_dir, model, prices, timeout, prompt=PROMPT):
    command = ["opencode", "run", "-m", model, "--auto", "--format", "json", prompt]
    events = os.path.join(cell_dir, "events.jsonl")
    with open(events, "w") as out, open(os.path.join(cell_dir, "stderr.log"), "w") as err:
        try:
            subprocess.run(command, cwd=cell_dir, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                           timeout=timeout, env=dict(os.environ, PWD=cell_dir))
        except subprocess.TimeoutExpired:
            pass
    tokens, _, _, _, text = parse_events("opencode", events)
    result = {"cost_catalog_usd": round(price(tokens, prices), 4), "reply": text}
    marker = text.rfind("RESULT_JSON:")
    if marker >= 0:
        try:
            result["scores"] = json.loads(text[marker + len("RESULT_JSON:"):].strip().splitlines()[0])
        except (ValueError, IndexError):
            pass
    with open(os.path.join(cell_dir, "review.json"), "w") as fh:
        json.dump(result, fh, indent=1)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--gold", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--prompt-file", help="replace the built-in code-review prompt (must end with a RESULT_JSON line)")
    args = parser.parse_args()

    with open(args.task) as fh:
        task = json.load(fh)
    prices = load_prices(args.model)
    prompt = open(args.prompt_file).read() if args.prompt_file else PROMPT
    sources = [(run, os.path.join(run, "solution.patch")) for run in args.runs]
    if args.gold:
        diff = subprocess.run(["git", "-C", task["repo"], "diff", task["base"], task["solution"], "--",
                               "src/main", "src/test", "specs", "docs"], capture_output=True, text=True,
                              check=True).stdout
        gold_path = os.path.join(args.out, "gold.patch")
        os.makedirs(args.out, exist_ok=True)
        with open(gold_path, "w") as fh:
            fh.write(diff)
        sources.append(("GOLD", gold_path))
    random.Random(args.seed).shuffle(sources)

    mapping = {}
    cells = []
    for index, (run, patch) in enumerate(sources, 1):
        label = "cell-%02d" % index
        cell_dir = os.path.join(args.out, "blind", label)
        os.makedirs(cell_dir, exist_ok=True)
        for source, name in ((patch, "change.patch"), (args.ticket, "ticket.md"), (args.key, "key.md")):
            with open(source, "rb") as src, open(os.path.join(cell_dir, name), "wb") as dst:
                dst.write(src.read())
        mapping[label] = run
        cells.append(cell_dir)
    with open(os.path.join(args.out, "mapping.json"), "w") as fh:
        json.dump(mapping, fh, indent=1)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda c: review(c, args.model, prices, args.timeout, prompt), cells))
    total = sum(r["cost_catalog_usd"] for r in results)
    print("reviewed %d cells, cost %.3f" % (len(results), total))


if __name__ == "__main__":
    main()
