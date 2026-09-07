---
name: git-commit
description: Create a git commit with the right message conventions (conventional prefix, [AI_Code] trailer on HelloFresh work repos). Use when the user asks to commit changes.
allowed-tools: Bash, Read
---

You're committing for the user. Be mechanical — the enforcement
(work-repo `[AI_Code]` tag, signing retry) lives in the script. Your
job is staging the right files and writing the message.

## Pre-flight

!`git status --short`

!`git diff --stat`

Only commit when the user has asked. Stage explicitly — `git add
<file>` for each intended file, never a blanket `git add -A`.

## Message

Conventional prefix: `feat:`, `fix:`, `chore:`, `docs:`,
`refactor:`, `test:`, `ci:`. One line, what + why — not a file list.

For work repos (`~/code/work/*`, hellofresh org), the commit message
itself must contain `[AI_Code]` — the org's auto-labeler
(`workflow-pr-label-for-ai-code`) only scans commit messages for that
literal string (or `[Cursor_Code]` / `<noreply@anthropic.com>`),
never the PR description, so a commit missing it gets no AI_Code
label. Add a trailer line:

```
[AI_Code] harness: <cli>, model: <model-id>
```

`harness` is the CLI producing the change (e.g. `opencode`,
`claude-code`); `model` is the model that generated the work.

## Commit

Call the script yourself via the Bash tool — substitute real values,
never paste literal placeholders:

```
~/code/personal/config/claude/scripts/commit.sh \
    -m "feat(x): ..." \
    -m "[AI_Code] harness: opencode, model: <model-id>"
```

The script refuses work-repo commits without `[AI_Code]` and retries
once without GPG signing if the signer fails. Parse `COMMIT_SHA=…`
from stdout.

## Respond to the user

One line: short SHA + subject.
