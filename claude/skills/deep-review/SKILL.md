---
name: deep-review
description: Deep-review a GitHub PR on code quality, correctness, hexagonal architecture, and anything else that stands out — every finding cross-checked against the live repo (not just the diff), written up as copy-pasteable comments in Avanindra's own tone, plus a final approve/request-changes call. Never posts anything to GitHub.
allowed-tools: Bash, Read, Grep, Glob, Agent
---

The user wants a PR reviewed. Extract the PR URL or `owner/repo#number` from
their message; if it's ambiguous which PR (e.g. they just say "review this"
with no link and no PR open in conversation), ask.

## Hard rule

**Never post anything to GitHub.** No `gh pr review`, no `gh pr comment`, no
`gh api ... -X POST` against comments/reviews endpoints — not even a draft
review, not even with `--body` empty. This skill only prints findings to the
chat. The user copy-pastes what they want, when they want. If you catch
yourself about to run a command that mutates the PR, stop.

## 1. Gather the target

```
gh pr view <target> --json title,body,author,baseRefName,headRefName,state,additions,deletions,changedFiles,labels
gh pr diff <target>
gh pr view <target> --json commits -q '.commits[] | .oid[0:8] + "  " + .committedDate + "  " + .messageHeadline'
```

If this is a re-review (the user already got a review earlier in this
conversation, or asks "did anything change" / "is there a new commit"):
compare the current commit list against the last one you looked at. If
there's a new commit, `gh api repos/<owner>/<repo>/commits/<sha> --jq
'.files[] | .patch'` to see just that commit's delta, and report explicitly
which of your prior findings it fixes vs. leaves open — don't just re-review
from scratch and silently drop the thread.

Also pull existing discussion before writing anything, so you don't repeat
settled points or re-litigate something the author already answered:

```
gh api repos/<owner>/<repo>/pulls/<number>/comments --jq '.[] | .user.login + " | " + .path + ":" + (.line|tostring) + " | id=" + (.id|tostring) + "\n" + .body + "\n---"'
gh api repos/<owner>/<repo>/pulls/<number>/reviews --jq '.[] | .user.login + " | " + .state + "\n" + .body'
```

If the author (or anyone) already addressed a concern in a reply thread,
say so and don't re-raise it as a fresh finding — note it as settled instead.

## 2. Verify against the live repo, not just the diff

The diff shows what changed, not whether the change is correct. For every
candidate finding, check it against actual state before writing it up:

- **Line numbers**: diff-relative line numbers lie once a file has more than
  one hunk. Pull the real file at the PR's head commit and count from that,
  or reconstruct hunks precisely — don't eyeball unified-diff line numbers.
  `gh api repos/<owner>/<repo>/contents/<path>?ref=<head_sha> -q .content | base64 -d`
  gets you the real file.
- **"Is this dead code?"** — grep the whole repo (not just the diff) for
  callers before flagging something as unused.
- **"Does this constraint/config still exist?"** — read the actual current
  file (migration, port interface, config), don't assume from the PR
  description.
- **"Is this actually N+1 / a hot path?"** — grep for call sites to see if
  it's invoked once per request or in a loop before calling it a performance
  problem. State what you found, not what you assume.
- Use the `Agent` tool (`Explore` type) for any of the above that needs
  broader searching than 2-3 greps can answer.

Findings that don't survive this check get dropped or downgraded, not
included for effect.

## 3. Review pillars

Cover all four, in this order, and anything else that jumps out doesn't need
its own pillar — bucket it under whichever fits best or add a short "Minor /
style" tail section:

1. **Code quality & style** — naming, duplication, unnecessary abstraction,
   comment hygiene (per the repo's CLAUDE.md if it has comment rules), ktlint-
   adjacent nits. Flag comments that just restate what a better function or
   variable name, or splitting a function into smaller well-named pieces,
   would already say — don't let those pass as fine just because they're
   present. A comment earns its place only when the logic encodes genuinely
   weird/non-obvious business rules that code structure alone can't express
   (a regulatory quirk, a workaround for another system's bug, a historical
   invariant) — that's the one place to *not* flag its absence or suggest
   removing it. Also flag PR/stack-relative framing in anything that outlives
   the PR — spec docs, ADRs, READMEs, code comments (`spec.md` saying "this
   PR" or "stacked directly on this PR", a comment saying "see the PR
   description"). Once merged to the trunk branch, the PR is gone from the
   reader's context but the doc/comment isn't — it should read fine cold, so
   point at the ticket instead of the PR.
2. **Correctness** — logic bugs, edge cases, race conditions, off-by-ones,
   whether tests actually cover what they claim to.
3. **Hexagonal architecture conventions** — for this codebase specifically:
   domain layer stays framework-free, ports vs. adapters aren't crossed
   without reason, application services orchestrate rather than contain
   business logic, adapters don't leak infra exceptions as domain-meaningful
   ones. Check the project's CLAUDE.md for the exact layer names/rules in use
   and hold the diff to those, not a generic textbook version.
4. **Anything else** — test coverage regressions (deleted tests with no
   replacement are a big one), performance (N+1, unnecessary full-row fetches
   where an EXISTS would do), security (injection, secret handling), and
   scope creep (unrelated changes bundled into a feature PR — but see the
   note below on when the user says to let something pass).

If the user has told you in this conversation to let a specific class of
finding pass ("letting X go", "don't flag Y"), don't re-raise it on a
re-review unless the underlying thing materially changed.

## 4. Output format

For each finding:

```
**N. <short title>**
`<file path>:<real line number>`
\`\`\`
<copy-pasteable comment text — see tone section>
\`\`\`
```

Group settled-by-discussion items separately from still-open ones. If this
is a re-review, lead with a one-line "what changed since last time" summary
before the finding list.

## 5. Tone for the comment text

Match Avanindra's own review-comment voice, not a generic formal reviewer's.
Real examples pulled from his PR history, to calibrate register:

- `sweet`
- `cool`
- `nice, way cleaner`
- `yes`
- `is okay, not sure if I like the changed function signature, could have been an object`
- `Looks like the signature became more complex`
- `Don't know why I added in the first placem is a private method, not needed in the interface`
- `will do this in improvement PR. It makes sense`
- `Not sure I agree 100%, this is to just verify if the save has worked as expected, but lemme chew on it and I might come around.`
- `Hmmm, keeping it nullable read better but this also works`

Takeaways for the comment text you generate:
- Short. A sentence or two, not a paragraph with a preamble.
- Direct opinions stated plainly — "not sure I agree", "is okay but", "makes
  sense" — rather than hedged corporate phrasing ("Could we possibly
  consider whether it might be preferable to...").
- When something's fine or a nice catch, a short positive reaction is a
  complete comment on its own — don't manufacture a nitpick to pad it out.
  Match the reaction to genuine weight, though: "nice" for a good renaming,
  "sweet"/"cool" for something that just works, not for a one-line import
  cleanup.
- Contractions, casual connectors ("but", "though", "lemme").
- Questions asked as genuine questions when you want their input, not as a
  soft way to disguise an instruction.
- No "As-is it'll bubble up as an unhandled 500"-style formal risk framing —
  say the same thing the way he would: "this'll blow up with a bare 500 if
  the planning group's gone, worth a proper exception here?"
- Still include the substance (what's wrong, what could happen) — tone
  changes the wrapping, not the content.

## 6. Final verdict

Close with an explicit call, one of: **Approve**, **Request changes**, or
**Comment only** — plus one or two sentences of reasoning (what would need
to change to flip an Approve, or why what's open isn't blocking). Base it on
severity, not count — one correctness bug outweighs five style nits.
