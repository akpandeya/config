---
name: pr-create
description: Open a PR for the requested repository and feature branch, respecting the current harness, repository policy and the user's publication scope.
allowed-tools: Bash, Read, Write
---

Check the repository, branch, intended base, status and unpushed commits first.
Do not publish unrelated work. If committing is not already authorized, ask
before committing and use the git-commit skill. Repository-specific ticket and
branch requirements come from private/project context; obtain the actual ticket
key before creating a branch when required.

Write a short body with `## Summary` and one to three meaningful bullets. Do not
pad it to a word count, list every file or add a Test plan unless asked. Include
the ticket reference in the repository's format and actual AI-tool attribution
when required; never copy a stale model name from an example.

Use the harness's native PR-creation tool when it is required. Respect its repo,
head and session scope: do not create a PR in the wrong repository, and do not
fall back to the shell when a native-tool failure does not authorize that.
If the harness permits CLI creation, use:

```bash
~/.config/agent-context/scripts/pr-create.sh --title "<actual title>" --body-file "<actual body file>"
```

Use the chosen base and draft state explicitly when needed. Personal PRs normally
open ready for review; work PRs remain drafts unless the user's policy says
otherwise. Read organization labels and attribution requirements from private
context, not hardcoded global defaults. Add only required labels and preserve
unrelated ones. Work PRs are human-merged.

Verify the returned PR belongs to the intended repository, branch and base.
Report its clickable URL and whether it is a draft. If publication is blocked,
say what exists locally/remotely and what did not succeed.
