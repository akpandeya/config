# Making issue-ship usable headless — status

Context: PR #11's `epic-ship.py` (deferred) drove a decomposed epic task by task with no
model in the outer loop, working around issue-ship with a long override block in its
session prompt. Those workarounds have since been moved into the skill as flags (see the
table) or made unnecessary by `issue-decompose` filing native sub-issues up front
(PR #14). Interactive behaviour with no flags is unchanged.

| Workaround in epic-ship.py | Resolution |
|---|---|
| Files each task file as a sub-issue first | **Unneeded** — `issue-decompose` files native sub-issues at decompose time (PR #14); every task already has an issue number. The `--task-file` idea is dead |
| Prompt says "already answered, never ask" | `IMPLEMENT= REVIEW= FIX= SHIP=` arguments (plus `ESCALATE=`/`FALLBACK=` via their flags); the skill asks only for what is missing |
| "Run every command in the foreground" | `--headless`: foreground runs, no AskUserQuestion, conservative choice where it would ask |
| Escalation ladder + merge-with-known-issues in the prompt | `--escalate=<h:m>` (up to 2 more rounds) and `--on-findings=stop|merge-with-followup`, default `stop`; verify red is never merged |
| "Retry once with the fallback" | `--fallback=<h:m>`, once per stage |
| Asks for `results/<task>.json` | Always writes `$SCRATCH/<issue>/result.json` and prints its path (contract below) |
| `briefs` in run-config | `--brief <file>` appended to the implement prompt and every review brief |

## Result contract

`$SCRATCH/<issue>/result.json`, written before the final report in every mode:

- `status`: `CLEAN` (review clean, not shipped) · `MERGED` ·
  `MERGED_WITH_KNOWN_ISSUES` · `STOPPED` (findings left with `--on-findings=stop`, or
  verify red after escalation) · `FAILED` (harness/setup failure)
- `pr`, `followUp`: URLs or empty strings
- `branch`: the task branch
- `notes`: at most 5 lines — rounds, escalation, conservative decisions, failure reason

An orchestrator (epic-ship/ship.py, jarvis autopilot) parses this file; keep the keys
exact.

## Still open

- Parallel tasks, stacked branches for unmerged dependencies, a shared ledger format
  with epic-drive: not worth doing yet.
- `epic-ship.py` (PR #11) shrinks to the loop, the skip rules and the result check when
  that workstream resumes; its locking/logging hardening is tracked separately.
