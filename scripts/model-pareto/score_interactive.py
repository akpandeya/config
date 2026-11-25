#!/usr/bin/env python3
"""Hard-grade and measure one finished interactive cell.

Usage: score_interactive.py --task TASK.json --run RUN_DIR [--timeout 1500] [--keep-colima]

Works on a copy of RUN_DIR/work. Overlays the grader tests (from the solution commit and/or local files named in the
manifest), compiles, runs the grader filters with the Docker environment exported, runs the agent's own new or
changed test classes, and measures quality signals from the unmodified work tree. Colima is started when needed and
stopped at the end. Writes RUN_DIR/score.json.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

DOCS_PREFIXES = ("specs/", "adrs/", "docs/")


def docker_env(task):
    env = dict(os.environ)
    defaults = {"DOCKER_HOST": "unix://$HOME/.colima/default/docker.sock",
                "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE": "/var/run/docker.sock"}
    for key, value in dict(defaults, **task.get("docker_env", {})).items():
        env[key] = os.path.expandvars(value)
    return env


def ensure_colima():
    if subprocess.run(["colima", "status"], capture_output=True).returncode != 0:
        subprocess.run(["colima", "start"], capture_output=True, check=True)


def gradle(tree, env, tasks, filters, timeout):
    command = ["./gradlew", "--console=plain", "-q"] + tasks
    for pattern in filters:
        command += ["--tests", pattern]
    try:
        done = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True, timeout=timeout)
        return done.returncode == 0, (done.stdout + done.stderr)[-2500:]
    except subprocess.TimeoutExpired:
        return False, "timed out"


def junit_results(tree, class_names):
    """Per-test outcome from Gradle's JUnit XML for the named test classes."""
    results = {}
    for path in glob.glob(os.path.join(tree, "build", "test-results", "test", "*.xml")):
        suite = ET.parse(path).getroot()
        if suite.get("name", "").rsplit(".", 1)[-1] not in class_names:
            continue
        for case in suite.iter("testcase"):
            failed = case.find("failure") is not None or case.find("error") is not None
            results[suite.get("name").rsplit(".", 1)[-1] + "." + case.get("name")] = (
                "skipped" if case.find("skipped") is not None else "fail" if failed else "pass")
    return results


def changed_files(work, base):
    """(status, path) for every file that differs from base, committed or not, untracked included."""
    entries = {}
    for line in subprocess.run(["git", "-C", work, "diff", "--name-status", base], capture_output=True, text=True).stdout.splitlines():
        status, _, path = line.partition("\t")
        entries[path.split("\t")[-1]] = status[0]
    for path in subprocess.run(["git", "-C", work, "ls-files", "-o", "--exclude-standard"], capture_output=True, text=True).stdout.splitlines():
        entries[path] = "A"
    return entries


def real_production_files(task):
    files = set()
    for commit in task.get("real_files_from", []):
        out = subprocess.run(["git", "-C", task["repo"], "show", "--name-only", "--format=", commit],
                             capture_output=True, text=True, check=True).stdout
        files.update(line for line in out.splitlines() if line.startswith("src/main/"))
    return files


def quality(task, work):
    base = task["base"]
    entries = changed_files(work, base)
    production = {p for p in entries if p.startswith("src/main/")}
    real = real_production_files(task)
    tests_added = sorted(p for p, s in entries.items() if p.startswith("src/test/") and s == "A")
    patch = subprocess.run(["git", "-C", work, "diff", base, "--", "src/test"], capture_output=True, text=True).stdout
    added_methods = len(re.findall(r"^\+\s*@(Test|ParameterizedTest)\b", patch, re.MULTILINE))
    spec_dirs = {}
    for path, status in entries.items():
        match = re.match(r"specs/(\d+-[^/]+)/(.+)", path)
        if match and status == "A":
            spec_dirs.setdefault(match.group(1), []).append(match.group(2))
    commits = subprocess.run(["git", "-C", work, "log", "--format=%s", base + "..HEAD"], capture_output=True,
                             text=True).stdout.splitlines()
    return {
        "production_files_changed": len(production),
        "production_files_outside_real_change": sorted(production - real),
        "real_production_files_untouched": sorted(real - production),
        "other_files_outside_src_and_docs": sorted(p for p in entries if not p.startswith("src/")
                                                   and not p.startswith(DOCS_PREFIXES)),
        "commit_count": len(commits), "commit_subjects": commits,
        "spec_dir_added": bool(spec_dirs), "spec_dirs": spec_dirs,
        "new_test_files": len(tests_added), "new_test_file_paths": tests_added,
        "test_methods_added": added_methods,
        "uncommitted_changes": bool(subprocess.run(["git", "-C", work, "status", "--porcelain"],
                                                   capture_output=True, text=True).stdout.strip()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--keep-colima", action="store_true")
    args = parser.parse_args()

    with open(args.task) as fh:
        task = json.load(fh)
    work = os.path.join(args.run, "work")
    score = {"quality": quality(task, work)}
    tree = os.path.join(args.run, "score-tree")
    if os.path.exists(tree):
        shutil.rmtree(tree)
    shutil.copytree(work, tree, symlinks=True)

    overlaid = []
    for relative in task.get("grade_files", []):
        blob = subprocess.run(["git", "-C", task["repo"], "show", task["solution"] + ":" + relative],
                              capture_output=True, check=True).stdout
        target = os.path.join(tree, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(blob)
        overlaid.append(relative)
    for overlay in task.get("grade_overlays", []):
        target = os.path.join(tree, overlay["to"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(overlay["from"], target)
        overlaid.append(overlay["to"])

    env = docker_env(task)
    try:
        ensure_colima()
        compiled, compile_log = gradle(tree, env, ["compileKotlin", "compileTestKotlin"], [], args.timeout)
        score["compiles"] = compiled
        if compiled:
            filters = task.get("unit_filters", []) + task.get("integration_filters", [])
            score["pass"], score["grader_log_tail"] = gradle(tree, env, ["test"], filters, args.timeout)
            classes = {f.strip("*") for f in filters}
            score["per_test"] = junit_results(tree, classes)
            score["tests_passed"] = sum(1 for v in score["per_test"].values() if v == "pass")
            score["tests_total"] = len(score["per_test"])
            own = sorted(p for p, s in changed_files(work, task["base"]).items()
                         if p.startswith("src/test/") and p.endswith("Test.kt") and p not in overlaid)
            own_classes = [os.path.basename(p)[:-3] for p in own]
            if own_classes:
                score["own_tests_pass"], score["own_tests_log_tail"] = gradle(
                    tree, env, ["test"], ["*" + c for c in own_classes], args.timeout)
                score["own_tests_classes"] = own_classes
        else:
            score["pass"] = False
            score["compile_log_tail"] = compile_log
    finally:
        if not args.keep_colima:
            subprocess.run(["colima", "stop"], capture_output=True)
    with open(os.path.join(args.run, "score.json"), "w") as fh:
        json.dump(score, fh, indent=1)
    print(json.dumps({k: v for k, v in score.items() if not k.endswith("_tail") and k != "per_test"}))


if __name__ == "__main__":
    main()
