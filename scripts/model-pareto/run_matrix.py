#!/usr/bin/env python3
"""Run and hard-grade every (model, harness) cell of a task, a few at a time, with a spend cap.

Usage: run_matrix.py --task TASK.json --out RUNS_DIR [--workers 4] [--budget-usd 25] [--timeout 1500]
                     [--models "provider/A,provider/B,..."] [--harnesses pi,opencode] [--tag matrix1]

Cells are queued in the order given (--models order), so the most informative models finish first.
A cell whose result.json already exists is skipped, so an interrupted matrix can be restarted.
When the summed catalog cost reaches --budget-usd, no new cell is started.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

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
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--budget-usd", type=float, default=25.0)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--models", default=",".join("ai-model-router/" + m for m in DEFAULT_MODELS))
    parser.add_argument("--harnesses", default="pi,opencode")
    parser.add_argument("--tag", default="matrix1")
    args = parser.parse_args()

    models = [m for m in args.models.split(",") if m]
    harnesses = [h for h in args.harnesses.split(",") if h]
    cells = [(m, h) for m in models for h in harnesses]
    lock = threading.Lock()
    spent = [0.0]
    log_path = os.path.join(args.out, args.tag + ".progress.log")
    os.makedirs(args.out, exist_ok=True)

    def note(message):
        with lock, open(log_path, "a") as fh:
            fh.write(message + "\n")

    def run(cell):
        model, harness = cell
        run_dir = os.path.join(args.out, "%s-%s-%s" % (args.tag, slug(model.split("/")[-1]), harness))
        with lock:
            if spent[0] >= args.budget_usd:
                note("SKIP budget reached: %s %s" % cell)
                return
        if os.path.exists(os.path.join(run_dir, "result.json")):
            note("SKIP exists: %s" % run_dir)
            return
        note("START %s %s" % cell)
        subprocess.run([sys.executable, os.path.join(HERE, "run_cell.py"), "--task", args.task, "--harness", harness,
                        "--model", model, "--out", run_dir, "--timeout", str(args.timeout)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cost = 0.0
        try:
            with open(os.path.join(run_dir, "result.json")) as fh:
                cost = json.load(fh)["cost_catalog_usd"]
        except (OSError, ValueError, KeyError):
            note("NO RESULT %s %s" % cell)
            return
        with lock:
            spent[0] += cost
        subprocess.run([sys.executable, os.path.join(HERE, "score_cell.py"), "--task", args.task, "--run", run_dir],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        note("DONE %s %s cost=%.3f total=%.3f" % (model, harness, cost, spent[0]))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, cells))
    note("ALL DONE total=%.3f" % spent[0])


if __name__ == "__main__":
    main()
