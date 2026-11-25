#!/usr/bin/env python3
"""Run one (task, harness, model) cell of the model Pareto pilot and record cost, time and a diff.

Usage: run_cell.py --task TASK.json --harness pi|opencode --model "provider/Model Name"
                   --out RUN_DIR [--timeout 1800] [--thinking LEVEL]

The task manifest (kept outside this repo) names a local git repo, a base commit and a prompt file.
The cell runs in a fresh local clone at the base commit, so the source repo is never modified.
Usage is read from each harness's JSON event stream, and cost is recomputed from the pi model
catalog so both harnesses are priced identically.
"""
import argparse
import json
import os
import subprocess
import sys
import time

PREAMBLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "claude", "scripts",
                        "implement-preamble.md")
CATALOG = os.path.expanduser("~/.pi/agent/models.json")


def load_prices(model_ref):
    """Return {input, output, cacheRead, cacheWrite} in USD per million tokens for 'provider/id'."""
    provider, _, model_id = model_ref.partition("/")
    with open(CATALOG) as fh:
        providers = json.load(fh).get("providers", {})
    for model in providers.get(provider, {}).get("models", []):
        if model.get("id") == model_id:
            return model["cost"]
    raise SystemExit("model not in catalog: " + model_ref)


def price(tokens, prices):
    per_million = (tokens["input"] * prices["input"] + tokens["output"] * prices["output"]
                   + tokens["cache_read"] * prices["cacheRead"] + tokens["cache_write"] * prices["cacheWrite"])
    return per_million / 1_000_000


def parse_events(harness, path):
    """Sum token usage and count tool calls from a harness JSON event stream."""
    tokens = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    reported_cost = 0.0
    tool_calls = 0
    turns = 0
    final_text = ""
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
                    if message.get("role") != "assistant":
                        continue
                    turns += 1
                    usage = message.get("usage") or {}
                    tokens["input"] += usage.get("input", 0)
                    tokens["output"] += usage.get("output", 0)
                    tokens["reasoning"] += usage.get("reasoning", 0)
                    tokens["cache_read"] += usage.get("cacheRead", 0)
                    tokens["cache_write"] += usage.get("cacheWrite", 0)
                    reported_cost += (usage.get("cost") or {}).get("total", 0.0)
                    content = message.get("content")
                    if isinstance(content, list):
                        tool_calls += sum(1 for block in content if block.get("type") == "toolCall")
                        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
                        if texts:
                            final_text = texts[-1]
            else:
                kind = event.get("type")
                part = event.get("part") or {}
                if kind == "step_finish":
                    turns += 1
                    usage = part.get("tokens") or {}
                    cache = usage.get("cache") or {}
                    tokens["input"] += usage.get("input", 0)
                    tokens["output"] += usage.get("output", 0)
                    tokens["reasoning"] += usage.get("reasoning", 0)
                    tokens["cache_read"] += cache.get("read", 0)
                    tokens["cache_write"] += cache.get("write", 0)
                    reported_cost += part.get("cost", 0.0)
                elif kind == "tool_use":
                    tool_calls += 1
                elif kind == "text":
                    final_text = part.get("text", final_text)
    return tokens, reported_cost, tool_calls, turns, final_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--harness", required=True, choices=["pi", "opencode"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--thinking", default="")
    args = parser.parse_args()

    with open(args.task) as fh:
        task = json.load(fh)
    prices = load_prices(args.model)
    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, "work")
    if os.path.exists(work):
        sys.exit("refusing to overwrite existing run: " + work)

    subprocess.run(["git", "clone", "-q", "--no-checkout", task["repo"], work], check=True)
    subprocess.run(["git", "-C", work, "checkout", "-q", task["base"]], check=True)
    subprocess.run(["git", "-C", work, "remote", "remove", "origin"], check=True)

    with open(PREAMBLE) as fh:
        prompt = fh.read() + "\n\n"
    with open(task["prompt_file"]) as fh:
        prompt += fh.read()

    if args.harness == "pi":
        command = ["pi", "-p", "--no-session", "--mode", "json", "--model", args.model]
        if args.thinking:
            command += ["--thinking", args.thinking]
        command.append(prompt)
    else:
        command = ["opencode", "run", "-m", args.model, "--agent", "coder", "--auto", "--format", "json", prompt]

    events_path = os.path.join(args.out, "events.jsonl")
    started = time.time()
    timed_out = False
    with open(events_path, "w") as out, open(os.path.join(args.out, "stderr.log"), "w") as err:
        try:
            completed = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       timeout=args.timeout, env=dict(os.environ, PWD=work))
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            exit_code, timed_out = 142, True
    wall_seconds = round(time.time() - started, 1)

    subprocess.run(["git", "-C", work, "add", "-N", "."], check=False)
    diff = subprocess.run(["git", "-C", work, "diff"], capture_output=True, text=True).stdout
    with open(os.path.join(args.out, "solution.patch"), "w") as fh:
        fh.write(diff)

    tokens, reported_cost, tool_calls, turns, final_text = parse_events(args.harness, events_path)
    result = {
        "task": task["id"], "harness": args.harness, "model": args.model, "thinking": args.thinking or "default",
        "exit_code": exit_code, "timed_out": timed_out, "wall_seconds": wall_seconds,
        "tokens": tokens, "cost_catalog_usd": round(price(tokens, prices), 4),
        "cost_reported_usd": round(reported_cost, 4), "tool_calls": tool_calls, "turns": turns,
        "diff_lines": diff.count("\n"), "final_reply_tail": final_text[-1500:],
    }
    with open(os.path.join(args.out, "result.json"), "w") as fh:
        json.dump(result, fh, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k != "final_reply_tail"}))


if __name__ == "__main__":
    main()
