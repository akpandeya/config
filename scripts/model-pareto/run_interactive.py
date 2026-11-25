#!/usr/bin/env python3
"""Run one (task, harness, model) cell as an interactive session: the agent may ask clarifying questions.

Usage: run_interactive.py --task TASK.json --harness pi|opencode --model "provider/Model Name" --out RUN_DIR
                          [--answerer-cmd CMD] [--max-rounds 3] [--timeout 5400] [--thinking LEVEL]

The task manifest names a local git repo, a base commit, a prompt file and a key file (the facts the stand-in
developer knows). Each round starts a fresh headless agent session in the SAME work tree. When the agent's final
reply starts with `QUESTIONS:` and it changed no files, the answerer command is called with the key and the
questions only (prompt on stdin, answer on stdout), the Q&A is appended to the prompt and the next round starts.
After --max-rounds answered rounds the agent gets one last round told to proceed on its own judgment.
Cost is summed over all rounds with the same pricing as run_cell.py; the answerer is counted, not priced.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_cell  # noqa: E402

DEFAULT_ANSWERER = 'claude -p --model sonnet --tools "" --disable-slash-commands --no-session-persistence'
ROLE = ("You are the developer who owns this ticket. Answer only from the key. If the key does not cover a "
        "question answer exactly: your call, follow the repo conventions. Be brief.")
QUESTIONS_RE = re.compile(r"^[ \t*#>]*QUESTIONS:", re.IGNORECASE | re.MULTILINE)
DOCKER_RE = re.compile(r"\b(colima|docker)\b", re.IGNORECASE)
TESTS_RE = re.compile(r"gradlew?\b[^\n]*\b(test|check|build)\b", re.IGNORECASE)


def git(work, *argv, check=True):
    return subprocess.run(["git", "-C", work] + list(argv), capture_output=True, text=True, check=check).stdout


def prepare_work(task, work):
    """Fetch only the base commit and its ancestors, so later commits of the source repo are not in the clone.
    The depth flag is needed because the source repo is itself a shallow clone."""
    os.makedirs(work)
    git(work, "init", "-q")
    git(work, "fetch", "-q", "--depth", "1000000", "--no-tags", task["repo"], task["base"])
    git(work, "checkout", "-q", "-b", "work", "FETCH_HEAD")
    for key, value in (("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                       ("user.name", "Model Pareto Agent"), ("user.email", "agent@example.invalid")):
        git(work, "config", key, value)


def tree_state(work):
    return git(work, "rev-parse", "HEAD").strip() + "\n" + git(work, "status", "--porcelain")


def build_prompt(base_prompt, qa, final_round):
    prompt = base_prompt
    if qa:
        prompt += "\n\n--- QUESTIONS ALREADY ASKED AND ANSWERED (earlier rounds; the repository keeps any files you wrote) ---\n"
        for number, (questions, answers) in enumerate(qa, 1):
            prompt += "\n[Round %d questions]\n%s\n\n[Round %d answers from the ticket owner]\n%s\n" % (
                number, questions.strip(), number, answers.strip())
        prompt += "--- END OF QUESTIONS AND ANSWERS ---\n"
    if final_round:
        prompt += "\nThe question budget is used up. Do not ask more questions; proceed on your own judgment now.\n"
    return prompt


def harness_command(harness, model, thinking, prompt):
    if harness == "pi":
        command = ["pi", "-p", "--no-session", "--mode", "json", "--model", model]
        if thinking:
            command += ["--thinking", thinking]
        return command + [prompt]
    return ["opencode", "run", "-m", model, "--agent", "coder", "--auto", "--format", "json", prompt]


def tool_call_text(harness, path):
    """All tool-call inputs of a harness event stream as one string (the prompt itself is excluded)."""
    chunks = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if harness == "pi":
                if event.get("type") != "agent_end":
                    continue
                for message in event.get("messages", []):
                    content = message.get("content")
                    if message.get("role") == "assistant" and isinstance(content, list):
                        chunks += [json.dumps(b.get("arguments")) for b in content if b.get("type") == "toolCall"]
            elif event.get("type") == "tool_use":
                chunks.append(json.dumps(((event.get("part") or {}).get("state") or {}).get("input")))
    return "\n".join(chunks)


def ask_answerer(answerer_cmd, key_text, questions, timeout=600):
    """Call the answerer with the key and the questions only. Returns the answer text."""
    prompt = "%s\n\n=== KEY ===\n%s\n\n=== QUESTIONS ===\n%s\n" % (ROLE, key_text, questions.strip())
    with tempfile.TemporaryDirectory() as empty:
        done = subprocess.run(shlex.split(answerer_cmd), input=prompt, capture_output=True, text=True,
                              cwd=empty, timeout=timeout)
    if done.returncode != 0 or not done.stdout.strip():
        raise RuntimeError("answerer failed rc=%s: %s" % (done.returncode, done.stderr[-500:]))
    return done.stdout.strip()


def run_round(args, work, prompt, events_path, stderr_path, deadline):
    remaining = max(60, int(deadline - time.time()))
    command = harness_command(args.harness, args.model, args.thinking, prompt)
    with open(events_path, "w") as out, open(stderr_path, "w") as err:
        try:
            done = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                  timeout=remaining, env=dict(os.environ, PWD=work))
            return done.returncode, False
        except subprocess.TimeoutExpired:
            return 142, True


def save_patches(work, out, base):
    git(work, "add", "-N", ".", check=False)
    files = {
        "solution.patch": git(work, "diff", base, check=False),
        "committed.patch": git(work, "diff", base + "..HEAD", check=False),
        "worktree.patch": git(work, "diff", "HEAD", check=False),
        "commits.txt": git(work, "log", "--format=%H%x09%s", base + "..HEAD", check=False),
    }
    for name, text in files.items():
        with open(os.path.join(out, name), "w") as fh:
            fh.write(text)
    return files["solution.patch"].count("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--harness", required=True, choices=["pi", "opencode"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--answerer-cmd", default=DEFAULT_ANSWERER)
    parser.add_argument("--max-rounds", type=int, default=3, help="answered question rounds allowed")
    parser.add_argument("--timeout", type=int, default=5400, help="total wall seconds over all rounds")
    parser.add_argument("--thinking", default="")
    args = parser.parse_args()

    with open(args.task) as fh:
        task = json.load(fh)
    prices = run_cell.load_prices(args.model)
    with open(task["prompt_file"]) as fh:
        base_prompt = fh.read()
    with open(task["key_file"]) as fh:
        key_text = fh.read()
    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, "work")
    if os.path.exists(work):
        sys.exit("refusing to overwrite existing run: " + work)
    prepare_work(task, work)

    started = time.time()
    deadline = started + args.timeout
    qa, rounds = [], []
    totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    totals_cost = totals_reported = 0.0
    tool_calls = turns = 0
    exit_code, timed_out, exit_state, final_text = 0, False, "completed", ""
    answerer_calls = 0
    all_events = os.path.join(args.out, "events.jsonl")
    open(all_events, "w").close()
    command_text = ""

    while True:
        number = len(rounds) + 1
        final_round = len(qa) >= args.max_rounds
        events_path = os.path.join(args.out, "events.round%d.jsonl" % number)
        before = tree_state(work)
        round_started = time.time()
        exit_code, timed_out = run_round(args, work, build_prompt(base_prompt, qa, final_round), events_path,
                                         os.path.join(args.out, "stderr.round%d.log" % number), deadline)
        tokens, reported, calls, round_turns, final_text = run_cell.parse_events(args.harness, events_path)
        for kind in totals:
            totals[kind] += tokens[kind]
        totals_cost += run_cell.price(tokens, prices)
        totals_reported += reported
        tool_calls += calls
        turns += round_turns
        command_text += "\n" + tool_call_text(args.harness, events_path)
        with open(events_path) as src, open(all_events, "a") as dst:
            dst.write(src.read())
        asked = bool(QUESTIONS_RE.search(final_text))
        changed = tree_state(work) != before
        rounds.append({"round": number, "asked": asked, "tree_changed": changed, "exit_code": exit_code,
                       "wall_seconds": round(time.time() - round_started, 1), "tokens": tokens,
                       "cost_catalog_usd": round(run_cell.price(tokens, prices), 4),
                       "tool_calls": calls, "turns": round_turns})
        if timed_out:
            exit_state = "timeout"
            break
        if not asked:
            exit_state = "completed" if exit_code == 0 else "harness_error"
            break
        if changed:
            exit_state = "questions_with_changes"
            break
        if final_round:
            exit_state = "asked_after_budget"
            break
        try:
            answers = ask_answerer(args.answerer_cmd, key_text, final_text)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            exit_state = "answerer_failed: %s" % error
            break
        answerer_calls += 1
        qa.append((final_text, answers))

    diff_lines = save_patches(work, args.out, task["base"])
    result = {
        "task": task["id"], "harness": args.harness, "model": args.model, "thinking": args.thinking or "default",
        "exit_state": exit_state, "exit_code": exit_code, "timed_out": timed_out,
        "rounds_used": len(rounds), "questions_per_round": [
            len(re.findall(r"^\s*\d+[.)]", q, re.MULTILINE)) for q, _ in qa] + (
            [len(re.findall(r"^\s*\d+[.)]", final_text, re.MULTILINE))] if exit_state in (
                "asked_after_budget", "questions_with_changes") else []),
        "questions_text": [q for q, _ in qa], "answers_text": [a for _, a in qa],
        "answerer_calls": answerer_calls, "answerer_priced": False,
        "wall_seconds": round(time.time() - started, 1), "tokens": totals,
        "cost_catalog_usd": round(totals_cost, 4), "cost_reported_usd": round(totals_reported, 4),
        "tool_calls": tool_calls, "turns": turns, "diff_lines": diff_lines, "per_round": rounds,
        "docker_attempted": bool(DOCKER_RE.search(command_text)), "tests_run": bool(TESTS_RE.search(command_text)),
        "final_reply_tail": final_text[-1500:],
    }
    with open(os.path.join(args.out, "result.json"), "w") as fh:
        json.dump(result, fh, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k not in ("final_reply_tail", "questions_text", "answers_text")}))


if __name__ == "__main__":
    main()
