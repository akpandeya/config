# Note: making issue-ship usable headless (not yet done)

Context: `claude/scripts/epic-ship.py` (first used for Olauncher #699, 2026-10-29) drives a
decomposed epic task by task with no model in the outer loop. It works around issue-ship
with a long override block in its session prompt. These are the workarounds, and the smallest
change to the skill that would make each one unnecessary. Aim for workable, not perfect:
add flags and keep today's interactive behaviour the default.

| Today | Workaround in epic-ship.py | Workable change to issue-ship |
|---|---|---|
| Needs a GitHub issue number | Files each task file as a sub-issue first | Accept `--task-file <path>` as the spec; the PR body then says `Ref #<epic>` instead of `Closes` |
| Asks the stage batch with AskUserQuestion | Prompt says "already answered, never ask" | Accept `IMPLEMENT= REVIEW= FIX= SHIP=` (and `ESCALATE= FALLBACK=`) as arguments; ask only for what is missing |
| Runs harness calls in the background and waits for notifications | "Run every command in the foreground" | A `--headless` mode: foreground runs, no questions, conservative choice where it would ask |
| Stops after 2 fix rounds with findings left | Escalation ladder + merge-with-known-issues in the prompt | `--escalate=<h:m>` (2 more rounds) and `--on-findings=stop|merge-with-followup`, default `stop` |
| Harness failure → ask again | "Retry once with the fallback" | `--fallback=<h:m>`, used once per stage |
| Free-text final report | Asks for `results/<task>.json` | Always write `$SCRATCH/<issue>/result.json` (`status, pr, followUp, branch, notes`); print its path |
| Per-task extras (bench run, content-review checklist, gate overrides) | `briefs` in run-config | `--brief <file>` appended to the implement and review prompts |

Once those exist, epic-ship.py shrinks to the loop, the skip rules and the result check, and
epic-drive could call issue-ship per task instead of re-implementing the stage loop.

Not worth doing yet: parallel tasks, stacked branches for unmerged dependencies, a shared
ledger format with epic-drive.
