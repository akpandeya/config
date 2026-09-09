---
name: pr-create
description: Open a PR from the current feature branch (right gh account, concise human-readable body).
allowed-tools: Bash, Read, Write
---

You're creating a PR for the user. Do it mechanically — the hard part
(gh account selection, push, create) is in the script.
Your job is just the PR body.

## Pre-flight

Check working tree:

!`git status --short`

!`git log --oneline -5`

If there are uncommitted changes, ask the user whether to commit them
first (don't auto-commit — user hasn't asked for that). If they want
them committed, use the `git-commit` skill — it owns the message
conventions (conventional prefix, the `[AI_Code]` trailer the
hellofresh auto-labeler requires in commit messages) and the commit
script.

## Write the PR body

Write a **concise** body to `/tmp/pr-body-$(date +%s).md`. Structure:

```
## Summary

- 1–3 bullets describing the *change*, not the files. Focus on what
  the user will notice or why this matters. No file-by-file lists.
```

Omit the Test plan section unless the user explicitly asks for one.
Never add it on your own judgment — not for "unusual" changes, not
"just in case."

If the branch name contains a Jira key (e.g. `feature/TGH-3550-...`),
add a ticket reference line after the summary, with the key in square
brackets so the Jira bot links the ticket:

```
Relates to [TGH-3550]
```

Do NOT include:
- Emojis (unless the user asked for them)
- Every modified filename
- Detailed changelog; the commit message carries that

DO include an attribution footer that identifies the AI tooling, in this shape:

```
Generated with AI [AI_Code] — harness: opencode, model: <model-id>
```

- `harness` is the CLI that produced the change (e.g. `opencode`).
- `<model-id>` is the model that generated the work (e.g. `deepseek-ai/DeepSeek-V4-Pro-0813`).
- Keep the `[AI_Code]` tag so it matches the repo's commit-message convention.

Keep the body succinct and human-readable, roughly 100–150 words.

## Open the PR

Call the script yourself via the Bash tool. Do NOT paste a literal
`<title>` / `<body-file>` — substitute the real values first. The
shape is:

```
~/code/personal/config/claude/scripts/pr-create.sh \
    --title "feat(x): ..." \
    --body-file /tmp/pr-body-1234567890.md
```

For work repos (hellofresh org), always pass `--draft` so the PR opens
as a draft. Personal repos open as ready for review.

Parse `PR_URL=…` and `PR_NUMBER=…` from stdout.

## Squad/tribe labels (hellofresh work repos)

Always add these labels on every work-repo PR:

```
gh pr edit <PR_NUMBER> --repo <org>/<repo> \
    --add-label "squad: production" --add-label "tribe: production-planning"
```

Check the labels exist first (`gh label list --repo <org>/<repo>`) —
label text sometimes differs slightly (spacing, renames). If either
label is missing in that repo, create it before adding it to the PR:

```
gh label create "squad: production" --repo <org>/<repo> --color "5319E7"
gh label create "tribe: production-planning" --repo <org>/<repo> --color "EBA726"
```

## Respond to the user

One or two lines: PR URL, done.
