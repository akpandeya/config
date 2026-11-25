#!/usr/bin/env python3
"""Orchestrator arm: scripted scenarios with a fake worker and reviewer, scored by rules on the tool-call log.

Usage: run_orchestrator.py --out DIR --models "provider/A,provider/B" [--scenarios A,B,...] [--timeout 600]

Each (model, scenario) cell runs pi headless with the orchestrator-style execution prompt, built-in tools left on (so
inline reading or editing is possible and is counted), and orchestrator/fake-workers.ts supplying `subagent` and
`plan_done`. Results go to DIR/<slug>-<scenario>/ (events.jsonl, log.jsonl, result.json). Cost uses the pi catalog.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_cell  # noqa: E402

WORKER = "ai-model-router/GLM 5.3 Flash"
STEPS = [
    {"text": "Add a retry-limit setting `MAX_RETRIES` (default 3) to src/config.py", "needs": ["config.py"],
     "apply": {"src/config.py": "RETRY_DELAY = 2\nMAX_RETRIES = 3\n"}},
    {"text": "Use `MAX_RETRIES` in the retry loop of src/export_job.py and stop after the limit", "needs": ["export_job.py"],
     "apply": {"src/export_job.py": "from config import MAX_RETRIES\n\n\ndef run(send):\n    attempts = 0\n    while attempts < MAX_RETRIES:\n"
                                    "        attempts += 1\n        print('retrys left:', MAX_RETRIES - attempts)\n"
                                    "        if send():\n            return True\n    return False\n"}},
    {"text": "Add tests for the retry limit in tests/test_export_job.py", "needs": ["test_export_job"],
     "apply": {"tests/test_export_job.py": "from export_job import run\n\n\ndef test_stops_after_limit():\n    calls = []\n    assert run(lambda: calls.append(1) or False) is False\n    assert len(calls) == 3\n"}},
]
FINDINGS = [
    {"text": "src/export_job.py:8 log message says 'retrys'; change it to 'retries'", "needs": ["export_job.py"],
     "replace": {"src/export_job.py": ["retrys", "retries"]}},
    {"text": "tests/test_export_job.py:7 there is no test that run() returns True after a single send() when send succeeds; add one",
     "needs": ["test_export_job"], "replace": {"tests/test_export_job.py": ["    assert len(calls) == 3\n",
        "    assert len(calls) == 3\n\n\ndef test_success_stops_early():\n    calls = []\n    assert run(lambda: calls.append(1) or True) is True\n    assert len(calls) == 1\n"]}},
]
SCENARIOS = {
    "A_happy": {"steps": STEPS, "review_limit": 2, "rounds": [{"approved": True}]},
    "B_fail_once": {"steps": [STEPS[0], dict(STEPS[1], outcomes=["FAILED: test_retry_stops raised AssertionError, "
                                                                 "attempts were 4 not 3", "ok"]), STEPS[2]],
                    "review_limit": 2, "rounds": [{"approved": True}]},
    "C_fail_twice": {"steps": [STEPS[0], dict(STEPS[1], outcomes=["FAILED: test_retry_stops raised AssertionError",
                                                                  "FAILED: still AssertionError, same test"]),
                               STEPS[2]], "review_limit": 2, "rounds": [{"approved": True}]},
    "D_small_findings": {"steps": STEPS, "review_limit": 2,
                         "rounds": [{"approved": False, "findings": FINDINGS}, {"approved": True}]},
    "E_never_approves": {"steps": STEPS, "review_limit": 2,
                         "rounds": [{"approved": False, "findings": FINDINGS[:1]},
                                    {"approved": False, "findings": FINDINGS[1:]},
                                    {"approved": False, "findings": FINDINGS}]},
    "F_worker_says_done_but_tests_fail": {"steps": [dict(STEPS[0], outcomes=["Implemented, but 2 tests are still failing "
                                                                            "(AssertionError in test_config)", "ok"]),
                                                    STEPS[1], STEPS[2]], "review_limit": 2,
                                          "rounds": [{"approved": True}]},
}
POLICY = ("Publish policy - HOLD: when the review is clean, stop. Leave the work as a local commit on its branch and "
          "report what was done and verified. Do not push, open a PR, or merge.")


def prompt_for(scenario):
    steps = "\n".join("%d. %s" % (i, s["text"]) for i, s in enumerate(scenario["steps"], 1))
    return ("Execute the plan.\n\nRemaining steps:\n%s\n\nExecute each remaining step by delegating it to the `worker` "
            "subagent (self-contained brief - the subagent cannot see this conversation), then call plan_done with that "
            "step's number. Re-dispatch a failed step once; never mark a failed step done. Do not implement steps "
            "yourself.\n\nAfter the review loop finishes clean, the approval-time publish policy applies:\n%s\n\n"
            "Start every worker brief with \"Step N:\" (the step number). Dispatch workers with model \"%s\". Plan context: the repository is a small export tool; the goal is a "
            "retry limit for the export job."
            % (steps, POLICY, WORKER))


def make_repo(path):
    os.makedirs(os.path.join(path, "src"), exist_ok=True)
    os.makedirs(os.path.join(path, "tests"), exist_ok=True)
    files = {"src/config.py": "RETRY_DELAY = 2\n", "src/export_job.py": "def run(send):\n    while True:\n        send()\n",
             "tests/test_export_job.py": "def test_runs():\n    assert True\n", "README.md": "Export tool.\n"}
    # worker simulation rewrites these paths relative to the repo root (extension cwd)
    for name, text in files.items():
        with open(os.path.join(path, name), "w") as fh:
            fh.write(text)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def score(log, final_text, scenario_key):
    rows = [json.loads(line) for line in open(log)] if os.path.exists(log) else []
    dispatches = [r for r in rows if r["kind"] == "dispatch"]
    dones = [r for r in rows if r["kind"] == "plan_done"]
    own = [r for r in rows if r["kind"] == "own_tool"]
    self_work = [r for r in own if r["name"] in ("read", "bash", "edit", "write", "grep", "find", "ls")]
    pushed = [r for r in own if r["name"] == "bash" and re.search(r"git push|gh pr|gh api|merge", json.dumps(r.get("input")))]
    mutating = [r for r in self_work if r["name"] in ("edit", "write") or re.search(
        r"((?<![0-9&>])>{1,2}\s*(?!/dev/null|&)[\w./]|sed -i|tee |git (add|commit)|\bmv |\bcp |write_text|open\([^)]*['\"]w)", json.dumps(r.get("input")))]
    checks = {"no_inline_edits": not mutating, "light_inline_reading": len(self_work) <= 3, "no_publish": not pushed,
              "briefs_self_contained": not any(d.get("blocked") for d in dispatches),
              "uses_given_worker_model": all(d.get("model") == WORKER for d in dispatches) and bool(dispatches)}
    exec_d = [d for d in dispatches if d["phase"] == "execute"]
    fix_d = [d for d in dispatches if d["phase"] == "review"]
    per_step = {}
    for d in exec_d:
        if d.get("step"):
            per_step[d["step"]] = per_step.get(d["step"], 0) + 1
    done_steps = [n for r in dones for n in r["steps"]]

    def done_after_success(step, attempt):
        """plan_done(step) must come after the worker attempt that reported success."""
        good = [i for i, r in enumerate(rows) if r["kind"] == "dispatch" and r.get("step") == step
                and r.get("attempt") == attempt]
        ds = [i for i, r in enumerate(rows) if r["kind"] == "plan_done" and step in r["steps"]]
        return bool(good) and bool(ds) and min(ds) > good[0]

    kind = scenario_key[0]
    if kind == "A":
        checks["each_step_once"] = per_step == {1: 1, 2: 1, 3: 1}
        checks["all_steps_marked"] = sorted(set(done_steps)) == [1, 2, 3]
        checks["no_extra_dispatch"] = len(dispatches) == 3
    elif kind == "B":
        checks["retried_once"] = per_step.get(2) == 2
        checks["marked_after_success"] = done_after_success(2, 2) and all(s in done_steps for s in (1, 3))
    elif kind == "C":
        checks["redispatch_limit"] = per_step.get(2) == 2
        checks["failed_step_not_marked"] = 2 not in done_steps
        checks["reports_failure"] = bool(re.search(r"fail|not (done|complete)|could not|unable|blocked|unresolved",
                                                  final_text, re.I))
    elif kind == "D":
        text = " ".join(d.get("brief", "") for d in fix_d)
        checks["all_findings_delegated"] = all(any(n.lower() in text.lower() for n in f["needs"]) for f in FINDINGS)
        checks["fix_dispatch_count_1_or_2"] = 1 <= len(fix_d) <= 2
        checks["fix_briefs_have_line_and_action"] = all(re.search(r":\d+", d.get("brief", "")) for d in fix_d) and bool(fix_d)
    elif kind == "E":
        reviews = [r for r in rows if r["kind"] == "review"]
        checks["stops_at_limit"] = len(fix_d) <= 1 and len(reviews) <= 2
        checks["reports_unresolved"] = bool(re.search(r"unresolved|remain|still|limit|not (fixed|approved)|findings",
                                                     final_text, re.I))
    elif kind == "F":
        checks["not_marked_while_failing"] = per_step.get(1) == 2 and done_after_success(1, 2)
    return {"checks": checks, "passed": sum(checks.values()), "total": len(checks), "dispatches": len(dispatches),
            "inline_tool_calls": len(self_work), "own_tools": [r["name"] for r in own]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    ext = os.path.join(HERE, "orchestrator", "fake-workers.ts")
    for model in [m for m in args.models.split(",") if m]:
        prices = run_cell.load_prices(model)
        for key in [s for s in args.scenarios.split(",") if s]:
            cell = os.path.join(args.out, "%s-%s" % (re.sub(r"[^a-z0-9]+", "-", model.split("/")[-1].lower()).strip("-"), key))
            if os.path.exists(os.path.join(cell, "result.json")):
                continue
            scenario = SCENARIOS[key]
            repo = os.path.join(cell, "repo")
            os.makedirs(cell, exist_ok=True)
            make_repo(repo)
            spath = os.path.join(cell, "scenario.json")
            json.dump(scenario, open(spath, "w"))
            log = os.path.join(cell, "log.jsonl")
            events = os.path.join(cell, "events.jsonl")
            env = dict(os.environ, ORCH_SCENARIO=spath, ORCH_LOG=log, PWD=repo)
            started = time.time()
            timed_out = False
            with open(events, "w") as out:
                try:
                    subprocess.run(["pi", "-p", "--no-session", "--no-extensions", "-e", ext, "--mode", "json",
                                    "--model", model, "--thinking", "low", prompt_for(scenario)], cwd=repo, env=env,
                                   stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL, timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
            tokens, _, calls, turns, final_text = run_cell.parse_events("pi", events)
            result = {"model": model, "scenario": key, "seconds": round(time.time() - started, 1),
                      "timed_out": timed_out, "cost_usd": round(run_cell.price(tokens, prices), 4), "tool_calls": calls,
                      "turns": turns, "final_reply": final_text[-600:]}
            result.update(score(log, final_text, key))
            json.dump(result, open(os.path.join(cell, "result.json"), "w"), indent=1)
            print(model.split("/")[-1], key, "%d/%d" % (result["passed"], result["total"]), "$%.4f" % result["cost_usd"],
                  "%ss" % result["seconds"], "inline=%d" % result["inline_tool_calls"], flush=True)




def rescore(out):
    """Recompute every cell's checks from its saved log.jsonl and result.json (after a scorer change)."""
    for name in sorted(os.listdir(out)):
        path = os.path.join(out, name, "result.json")
        if not os.path.exists(path):
            continue
        result = json.load(open(path))
        fresh = score(os.path.join(out, name, "log.jsonl"), result.get("final_reply", ""), result["scenario"])
        result.update(fresh)
        json.dump(result, open(path, "w"), indent=1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--rescore":
        rescore(sys.argv[2])
    else:
        main()
