#!/usr/bin/env python3
"""Run and score interactive cells one at a time (they share one Docker), with a spend cap.

Usage: run_interactive_matrix.py --task TASK.json --out RUNS_DIR [--budget-usd 25] [--timeout 5400]
                                 [--models "provider/A,provider/B"] [--harnesses pi,opencode] [--tag inter1]
                                 [--max-rounds 3] [--answerer-cmd CMD]

Before each cell Colima is stopped, so the agent has to find out how to start Docker itself. After the
cell the scorer starts Colima, grades, and stops it again. A cell whose result.json exists is skipped.
When the summed catalog cost reaches --budget-usd no new cell is started.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODELS = [
    "GPT-6 Luna", "GPT-6.1 Terra", "GPT-6.2 Sol", "Claude Opus 5.5",
    "Claude Sonnet 5.5", "Kimi K3.1 Pro", "Claude Haiku 5.5", "GLM 5.3 Flash",
]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--budget-usd", type=float, default=25.0)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--models", default=",".join("ai-model-router/" + m for m in DEFAULT_MODELS))
    parser.add_argument("--harnesses", default="pi,opencode")
    parser.add_argument("--tag", default="inter1")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--answerer-cmd", default="")
    args = parser.parse_args()

    models = [m for m in args.models.split(",") if m]
    harnesses = [h for h in args.harnesses.split(",") if h]
    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, args.tag + ".progress.log")
    spent = 0.0

    def note(message):
        with open(log_path, "a") as fh:
            fh.write(message + "\n")

    for model in models:
        for harness in harnesses:
            cell = (model, harness)
            run_dir = os.path.join(args.out, "%s-%s-%s" % (args.tag, slug(model.split("/")[-1]), harness))
            if spent >= args.budget_usd:
                note("SKIP budget reached: %s %s" % cell)
                continue
            if os.path.exists(os.path.join(run_dir, "result.json")):
                note("SKIP exists: %s" % run_dir)
                continue
            note("START %s %s" % cell)
            subprocess.run(["colima", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            command = [sys.executable, os.path.join(HERE, "run_interactive.py"), "--task", args.task,
                       "--harness", harness, "--model", model, "--out", run_dir, "--timeout", str(args.timeout),
                       "--max-rounds", str(args.max_rounds)]
            if args.answerer_cmd:
                command += ["--answerer-cmd", args.answerer_cmd]
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                with open(os.path.join(run_dir, "result.json")) as fh:
                    cost = json.load(fh)["cost_catalog_usd"]
            except (OSError, ValueError, KeyError):
                note("NO RESULT %s %s" % cell)
                continue
            spent += cost
            subprocess.run([sys.executable, os.path.join(HERE, "score_interactive.py"), "--task", args.task,
                            "--run", run_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["colima", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            note("DONE %s %s cost=%.3f total=%.3f" % (model, harness, cost, spent))
    note("ALL DONE total=%.3f" % spent)


if __name__ == "__main__":
    main()
