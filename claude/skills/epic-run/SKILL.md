---
name: epic-run
description: >-
  Run a GitHub issue or epic end to end: pick the harness and model for the decomposer,
  the implementer and the epic reviewer, then decompose, drive every task to merge, and
  review the whole epic once. Entry point for issue-decompose, epic-drive and epic-review.
  Usage: /epic-run [<owner/repo> <issue-number>] [--retry-failed]
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion, Skill
argument-hint: "[<owner/repo> <issue-number>] [--retry-failed]"
---

One entry point for the whole pipeline. It asks three role questions and one pacing question (who decomposes, who implements,
who reviews the epic), then runs the three components in order. Each component can still be run on
its own: `issue-decompose`, `epic-drive` and `epic-review`.

Publishing is part of this explicitly invoked end-to-end workflow. Work-repo merges still belong to
a human. A plan-only invocation stops before execution.

## 1. Discover models

Run:

```bash
~/.config/agent-context/scripts/list-models.sh all
```

It prints `<harness><TAB><model>` lines. It makes no model calls and costs nothing, so run it every
time. If the script is missing, say so and stop: the install step has not run.

## 2. Pick harnesses

Ask the three role questions and the cool-down question in one `AskUserQuestion` call (four questions).
If the tool allows fewer than four questions per call, ask the cool-down question in a separate call.

For the three role questions, the options are the three harnesses, each with a short description:

- **Claude Code**: Claude models through `claude`
- **OpenCode**: models from the local `opencode` config
- **Antigravity (agy)**: Gemini and Claude models through `agy`

Roles, with their header labels:

- `Decomposer`: writes the task prompts. Opus-class reasoning helps most here.
- `Implementer`: writes the code for each task, one PR per task.
- `Reviewer`: reviews the whole epic after its last merge and fixes what it finds, in rounds until a round changes nothing.

The fourth question, header `Cool-down`: "Cool-down between tasks?" Options:

- **Use manifest value**: use `cooldownSeconds` from the manifest. Offer it first only when a manifest
  exists and sets `cooldownSeconds`; otherwise leave it out.
- **0 seconds**: no pause
- **540 seconds**: default, rate-limit friendly
- **900 seconds**

The answer is passed to `epic-drive` as `COOLDOWN=<seconds>` (or `COOLDOWN=manifest`). Nothing assumes a
default silently.

## 3. Pick models

For each role, list the models for its chosen harness from step 1. Ask all three model questions in
one second `AskUserQuestion` call. Offer at most four options per question, plus the built-in "Other"
for the rest. Put the most capable model first and mark it "(Recommended)" only for the decomposer and
reviewer when the harness offers an Opus-class model.

Models change between work and personal profiles, so never hardcode a list here. The live list is the
only source.

## 4. Confirm

Print a three-row table: role, harness, model, and a line below it with the chosen cool-down in seconds. Then continue without asking again, unless step 5 needs a
confirmation.

Notes:
- If the decomposer and the implementer are the same harness, the decomposer is a same-harness subagent.
  Otherwise use the headless helper. The same rule applies to the reviewer.
- If the harness is the one running this session, use that harness's own subagent tool. Do not shell out
  to a CLI for it.

## 5. Run the pipeline

Resolve `$REPO`, `$ISSUE_NUM` and `$PROMPT_DIR` as `issue-decompose` does. With no epic given, skip to the
run-all form in `epic-drive`.

1. **Decompose.** If `$PROMPT_DIR/manifest.json` already exists, do not decompose again. Show its task list
   and ask whether to keep it or re-decompose. Re-decomposing a partly-run epic is refused while any task
   is `pr_open`, `merged` or `running`. Otherwise run the `issue-decompose` skill with `DECOMPOSER=<harness>:<model>`.
2. **Drive.** Run the `epic-drive` skill with `IMPLEMENTER=<harness>:<model>`, `COOLDOWN=<seconds>` and any `--retry-failed`.
   It stops at a halt and resumes on re-run, so a halt here is the normal stop point.
3. **Review.** `epic-drive` runs the `epic-review` skill itself as its final step, with
   `REVIEWER=<harness>:<model>`. Pass the reviewer to `epic-drive` so it can do that. If `epic-drive` reports
   every task merged without having reviewed, run `epic-review` here.

Stop at any halt and print the resume command for the component that stopped. Do not run a later step
after an earlier one halted.

## Final report

The three-row role table, then the reports the components return: task table, epic review verdict, and
any resume command.
