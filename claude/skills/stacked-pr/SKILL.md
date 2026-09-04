---
name: stacked-pr
description: Manage a stacked-PR chain in a work repo — link an existing manual stack, sync it safely when a lower PR merges, or check status. Wraps the gh-stack extension.
allowed-tools: Bash, Read
---

The user has (or wants) a chain of PRs where each one's base is the branch below
it (e.g. `feature/TICKET-1-schema` → `feature/TICKET-2-backend` →
`feature/TICKET-3-web`, one PR per branch). HelloFresh repos build these
manually today, by convention, not tooling. `gh stack` (official extension,
`github/gh-stack`) wraps that with real tracking, sync, and status. Install
once if missing: `gh extension install github/gh-stack`.

If the repo's git remote uses an SSH host alias (e.g. `git@github.com-work:org/repo`
via `~/.ssh/config`, rather than the plain `github.com` host), `gh stack`'s own
repo-detection can fail with "unable to determine current repository" even
though `gh pr create`/`gh api` work fine. Fix: prefix every `gh stack` command
with `GH_REPO=<owner>/<repo>` (e.g. `GH_REPO=hellofresh/fulfilment-demand-allocator
gh stack rebase`) — cheaper to just `export GH_REPO=...` once per session.

## Pick the entry point

- **New stack, not yet pushed**: `gh stack init` on the trunk, then `gh stack
  add <branch>` per layer, `gh stack submit` to push + open all the PRs at once.
- **Existing manual stack, PRs already open** (the common case here — this
  repo's convention predates the extension): `gh stack link <pr1> <pr2> <pr3>`
  (bottom to top, by PR number or URL). This is the retrofit path — it doesn't
  touch branches, just registers the chain on GitHub. **Ask the user before
  running this against real open PRs** — it adds visible stack UI to PRs other
  people are reviewing.
- **Status check**: `gh stack view` (or `--short` / `--json`).
- **A lower PR in the stack just merged**: this is the dangerous moment — see
  below, handle it before pushing anything else in the stack.

## The merge-forward gotcha this skill exists for

Two distinct triggers produce the same symptom — the bottom PR of the stack
shows `mergeStateStatus: DIRTY` / `mergeable: CONFLICTING` on GitHub:

1. **A lower PR in the same stack merges.** GitHub squash-merges it and
   force-rewrites every downstream branch's remote history onto the new trunk
   tip, retargeting the next PR's base. A plain `git push` on the downstream
   branch gets rejected ("fetch first").
2. **An unrelated PR merges to trunk first**, touching the same files as the
   bottom of the stack (real-world case: someone else's PR landed on `master`
   with conflicting changes to a file our stack's bottom PR also touched).
   Nothing about the stack's own PRs changed — trunk just moved past it.

Either way, once the stack is registered (`gh stack link` or `gh stack init`
was run), the recovery is the same and doesn't require `gh stack sync`
(`sync` is for pulling *remote* stack-metadata changes into your local view —
not the tool for cascading a rebase across branches):

```
gh stack checkout <stack-id-or-any-pr-number>   # re-imports the stack locally if needed
gh stack rebase                                  # cascades: rebases branch 1 onto trunk,
                                                  # branch 2 onto rebased branch 1, etc.
# on conflict: resolve in the listed file(s), `git add`, then:
gh stack rebase --continue
# repeat resolve/continue until it reports all branches rebased
```

Note: `gh stack checkout <id>` works even when `gh stack view`/`list` claim
"current branch is not part of a stack" right after a `gh stack link` — `link`
registers the stack server-side without writing local tracking state, and
`checkout` is what actually re-imports it locally. Don't take that "not part
of a stack" error as proof the link failed.

If a conflict resolution touches a commit that isn't the tip (e.g. the fix
belongs semantically to an earlier layer's commit, and just leaving it as a
new commit on the tip would put the fix in the wrong PR): `git checkout
<that-layer's-branch>`, apply the fix, `git commit --amend`, then run `gh
stack rebase` again from the top of the stack — it re-cascades the amendment
through every branch above it, including re-detecting conflicts if any.

After a clean `gh stack rebase`, **run the full build/test/lint gate on the
stack tip before pushing** — a structural rebase can auto-merge text cleanly
while still leaving a semantic break (e.g. one layer renamed a field, and a
file merged from trunk still uses the old name) that only compiling/testing
catches.

Then push the whole stack: `gh stack push` (force-with-lease per branch,
handled for you). Verify with `gh pr view <bottom-pr> --json
mergeable,mergeStateStatus` — expect `MERGEABLE` (an unrelated `BLOCKED`
status just means required checks/reviews, not a conflict).

If the stack is **not** registered (plain manual chain, no `gh stack link`/
`init` ever run): before pushing anything to the downstream branch, run `git
fetch origin <branch>` and check for a "forced update" line, and `gh pr view
<downstream-pr> --json baseRefName` for an unexpected retarget. If either
shows up:
1. Confirm any local-only commit with the actual fix is safe (`git branch -r
   --contains <sha>` — if it's on some other remote branch, or nowhere, it's
   still recoverable; don't reset before checking this).
2. `git reset --hard origin/<branch>` to resync to GitHub's rewritten history.
3. Cherry-pick the local-only fix commit(s) back on top.
4. Re-run the build/test gate, then push — this time it should fast-forward.

## Respond to the user

State which entry point you used and the resulting stack state (from `gh stack
view --short` if one exists) in 2-3 lines. Don't narrate the mechanics unless
the merge-forward recovery above was needed — call that out explicitly if it
was, since it's a real risk moment, not routine.
