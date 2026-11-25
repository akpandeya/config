#!/usr/bin/env python3
"""Compaction-summary arm: can a cheap model's summary of a long session answer questions about it?

Usage: run_compaction.py prepare --session SESSION.jsonl --out DIR [--max-chars 350000]
       run_compaction.py questions --out DIR --model "provider/Model" [--count 10]
       run_compaction.py summarize --out DIR --models "provider/A,provider/B" [--timeout 900]
       run_compaction.py grade --out DIR

prepare   serialises the first --max-chars characters of a pi session (messages only, tool output truncated).
questions a strong model (OpenCode) reads the excerpt and writes questions with gold answers a continuing agent
          would need (decisions, numbers, file names, open items), as DIR/qa.json.
summarize each model gets the same summarisation prompt the background-compaction extension uses, on pi with no
          tools, and writes DIR/summaries/<slug>.json (text, cost, seconds).
grade     a fixed answerer (claude -p sonnet, no tools) answers every question from ONLY the summary, a fixed grader
          marks each answer 0/1 against the gold answer, and DIR/grades.json lists per-model correct counts.
          The answerer and grader are not priced.
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

SUMMARY_PROMPT = """You are a conversation summarizer. Create a comprehensive summary of this conversation that captures:

1. The main goals and objectives discussed
2. Key decisions made and their rationale
3. Important code changes, file modifications, or technical details
4. Current state of any ongoing work
5. Any blockers, issues, or open questions
6. Next steps that were planned or suggested

Be thorough but concise. The summary will replace this portion of the conversation history, so include all information needed to continue the work effectively. Recent messages near the end are kept verbatim separately; focus on everything up to and including the last completed exchange.

Format the summary as structured markdown with clear sections.

<conversation>
%s
</conversation>"""
CLAUDE = 'claude -p --model sonnet --tools "" --disable-slash-commands --no-session-persistence'


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind == "toolCall":
            parts.append("[tool call %s %s]" % (block.get("name"), json.dumps(block.get("arguments"))[:400]))
    return "\n".join(parts)


def prepare(args):
    os.makedirs(args.out, exist_ok=True)
    out, size = [], 0
    with open(args.session) as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message")
            if entry.get("type") != "message" or not message:
                continue
            role = message.get("role")
            text = text_of(message.get("content"))
            if role == "toolResult":
                text = "[tool result] " + text[:1200]
            elif not text.strip():
                continue
            chunk = "[%s]\n%s\n" % (role, text.strip())
            if size + len(chunk) > args.max_chars:
                break
            out.append(chunk)
            size += len(chunk)
    with open(os.path.join(args.out, "excerpt.txt"), "w") as fh:
        fh.write("\n".join(out))
    print("excerpt chars", size, "messages", len(out))


def questions(args):
    qdir = os.path.join(args.out, "qa_work")
    os.makedirs(qdir, exist_ok=True)
    with open(os.path.join(args.out, "excerpt.txt")) as src, open(os.path.join(qdir, "excerpt.txt"), "w") as dst:
        dst.write(src.read())
    prompt = ("Read excerpt.txt (a long agent session; do not edit anything). Write %d questions that an agent "
              "CONTINUING this work would need answered, each with a short gold answer taken from the text: concrete "
              "decisions and their reason, specific numbers, file or function names, what was ruled out, and open "
              "items. Spread them across the whole excerpt, early, middle and late. Avoid questions answerable from "
              "general knowledge. Finish with ONE line of JSON and nothing after it: "
              'QA_JSON: [{"q": "...", "gold": "..."}, ...]' % args.count)
    prices = run_cell.load_prices(args.model)
    events = os.path.join(qdir, "events.jsonl")
    with open(events, "w") as out:
        subprocess.run(["opencode", "run", "-m", args.model, "--auto", "--format", "json", prompt], cwd=qdir,
                       stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL, timeout=1200,
                       env=dict(os.environ, PWD=qdir))
    tokens, _, _, _, text = run_cell.parse_events("opencode", events)
    marker = text.rfind("QA_JSON:")
    qa = json.loads(text[marker + len("QA_JSON:"):].strip().splitlines()[0])
    with open(os.path.join(args.out, "qa.json"), "w") as fh:
        json.dump({"qa": qa, "cost_usd": round(run_cell.price(tokens, prices), 4)}, fh, indent=1)
    print("questions", len(qa), "cost", round(run_cell.price(tokens, prices), 4))


def summarize(args):
    os.makedirs(os.path.join(args.out, "summaries"), exist_ok=True)
    with open(os.path.join(args.out, "excerpt.txt")) as fh:
        excerpt = fh.read()
    prompt = SUMMARY_PROMPT % excerpt
    for model in [m for m in args.models.split(",") if m]:
        path = os.path.join(args.out, "summaries", slug(model.split("/")[-1]) + ".json")
        if os.path.exists(path):
            continue
        prices = run_cell.load_prices(model)
        events = path + ".events"
        started = time.time()
        with open(events, "w") as out:
            try:
                subprocess.run(["pi", "-p", "--no-session", "--no-tools", "--mode", "json", "--model", model, prompt],
                               stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL, timeout=args.timeout)
            except subprocess.TimeoutExpired:
                pass
        tokens, _, _, _, text = run_cell.parse_events("pi", events)
        with open(path, "w") as fh:
            json.dump({"model": model, "seconds": round(time.time() - started, 1), "tokens": tokens,
                       "cost_usd": round(run_cell.price(tokens, prices), 4), "summary": text}, fh, indent=1)
        print(model, round(time.time() - started), "s", round(run_cell.price(tokens, prices), 4), "usd", len(text), "chars")


def claude(prompt):
    with tempfile.TemporaryDirectory() as empty:
        return subprocess.run(shlex.split(CLAUDE), input=prompt, capture_output=True, text=True, cwd=empty,
                              timeout=900).stdout.strip()


def grade(args):
    with open(os.path.join(args.out, "qa.json")) as fh:
        qa = json.load(fh)["qa"]
    numbered = "\n".join("%d. %s" % (i, item["q"]) for i, item in enumerate(qa, 1))
    results = {}
    directory = os.path.join(args.out, "summaries")
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(directory, name)) as fh:
            record = json.load(fh)
        answers = claude("Answer each question using ONLY the summary below. If the summary does not say, answer "
                         "exactly: NOT IN SUMMARY. One line per answer, numbered.\n\n=== SUMMARY ===\n%s\n\n"
                         "=== QUESTIONS ===\n%s\n" % (record["summary"], numbered))
        gold = "\n".join("%d. Q: %s | GOLD: %s" % (i, item["q"], item["gold"]) for i, item in enumerate(qa, 1))
        verdict = claude("Grade each candidate answer against the gold answer: 1 if it states the same key fact "
                         "(wording may differ), else 0. Reply with ONE line of JSON only: [1,0,...] with one entry "
                         "per question in order.\n\n=== GOLD ===\n%s\n\n=== CANDIDATE ANSWERS ===\n%s\n" % (gold, answers))
        try:
            marks = json.loads(re.search(r"\[[\d,\s]*\]", verdict).group(0))
        except (AttributeError, ValueError):
            marks = []
        results[name[:-5]] = {"correct": sum(marks), "of": len(qa), "marks": marks, "cost_usd": record["cost_usd"],
                              "seconds": record["seconds"], "summary_chars": len(record["summary"])}
    with open(os.path.join(args.out, "grades.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    for name, row in results.items():
        print(name, "%d/%d" % (row["correct"], row["of"]), "$%.4f" % row["cost_usd"], "%ss" % row["seconds"])


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="step", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--session", required=True); p.add_argument("--out", required=True)
    p.add_argument("--max-chars", type=int, default=350000)
    q = sub.add_parser("questions"); q.add_argument("--out", required=True); q.add_argument("--model", required=True)
    q.add_argument("--count", type=int, default=10)
    s = sub.add_parser("summarize"); s.add_argument("--out", required=True); s.add_argument("--models", required=True)
    s.add_argument("--timeout", type=int, default=900)
    g = sub.add_parser("grade"); g.add_argument("--out", required=True)
    args = parser.parse_args()
    {"prepare": prepare, "questions": questions, "summarize": summarize, "grade": grade}[args.step](args)


if __name__ == "__main__":
    main()
