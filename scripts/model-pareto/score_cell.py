#!/usr/bin/env python3
"""Hard-grade one finished cell: overlay the real PR's tests, compile, run the named test filters.

Usage: score_cell.py --task TASK.json --run RUN_DIR [--integration] [--timeout 1500]

Works on a copy of the cell's work tree, so the recorded solution stays untouched. Integration
filters need Docker (Testcontainers) and run only with --integration.
"""
import argparse
import json
import os
import shutil
import subprocess


def gradle(tree, tasks, filters, timeout):
    command = ["./gradlew", "--console=plain", "-q"] + tasks
    for pattern in filters:
        command += ["--tests", pattern]
    try:
        completed = subprocess.run(command, cwd=tree, capture_output=True, text=True, timeout=timeout)
        return completed.returncode == 0, (completed.stdout + completed.stderr)[-2500:]
    except subprocess.TimeoutExpired:
        return False, "timed out"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--timeout", type=int, default=1500)
    args = parser.parse_args()

    with open(args.task) as fh:
        task = json.load(fh)
    tree = os.path.join(args.run, "score-tree")
    if os.path.exists(tree):
        shutil.rmtree(tree)
    shutil.copytree(os.path.join(args.run, "work"), tree, symlinks=True)

    for relative in task["grade_files"]:
        blob = subprocess.run(["git", "-C", task["repo"], "show", task["solution"] + ":" + relative],
                              capture_output=True, check=True).stdout
        target = os.path.join(tree, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(blob)

    compiled, compile_log = gradle(tree, ["compileKotlin", "compileTestKotlin"], [], args.timeout)
    score = {"compiles_with_real_tests": compiled}
    if compiled:
        score["unit_pass"], score["unit_log_tail"] = gradle(tree, ["test"], task["unit_filters"], args.timeout)
        if args.integration:
            score["integration_pass"], score["integration_log_tail"] = gradle(
                tree, ["test"], task["integration_filters"], args.timeout)
    else:
        score["compile_log_tail"] = compile_log
    with open(os.path.join(args.run, "score.json"), "w") as fh:
        json.dump(score, fh, indent=1)
    print(json.dumps({k: v for k, v in score.items() if not k.endswith("_tail")}))


if __name__ == "__main__":
    main()
