---
name: deep-review
description: Deep-review a GitHub PR or stack with verified findings, a plain-language walkthrough of the changed behavior and every finding, short copy-pasteable comments in Avanindra's voice, and an evidence-based verdict. Use for PR reviews and re-reviews. Never posts anything to GitHub.
allowed-tools: Bash, Read, Write, Grep, Glob, Agent
---

The user wants a PR reviewed. Extract the PR URL or `owner/repo#number` from
their message; if it's ambiguous which PR (e.g. they just say "review this"
with no link and no PR open in conversation), ask.

## Hard rule

**Never post anything to GitHub.** No `gh pr review`, no `gh pr comment`, no
`gh api ... -X POST` against comments/reviews endpoints — not even a draft
review, not even with `--body` empty. This skill reports findings in chat and,
for substantial reviews, a local HTML explanation outside Git. The user
copy-pastes what they want, when they want. If you catch
yourself about to run a command that mutates the PR, stop.

## 1. Pin the target

Pin exact versions up front so every later command inspects the same code:

```
gh pr view <target> --json title,body,author,baseRefName,headRefName,state,additions,deletions,changedFiles,labels,baseRefOid,headRefOid
gh pr view <target> --json commits -q '.commits[] | .oid[0:8] + "  " + .committedDate + "  " + .messageHeadline'
gh api "repos/<owner>/<repo>/compare/<baseRefOid>...<headRefOid>" --jq .merge_base_commit.sha
```

- Use the pinned SHAs everywhere — never moving branch names. The review
  base is the **merge base** of the pinned base and head commits (the
  compare call above), not the base-branch tip.
- Get the diff between the pinned merge base and pinned head with
  `git diff <merge_base> <head_sha>` (fetch the two exact objects first), or
  the pinned API equivalent
  `gh api "repos/<owner>/<repo>/compare/<merge_base>...<head_sha>"`. Never
  substitute a current `gh pr diff` — it follows moving branch tips and is
  wrong for a pinned or historical review. The compare API truncates large
  file patches — if a changed file shows no visible patch or the diff looks
  cut off, fall back to the local git diff before reviewing that file.
- Quote API URLs containing `?` — zsh glob-expands them otherwise:
  `gh api "repos/<owner>/<repo>/contents/<path>?ref=<head_sha>" -q .content | base64 -d`
  fetches a file at the pinned head.
- If the user explicitly supplies a historical revision (a SHA, or "review
  commit X"), review that revision instead of the current head: diff it
  against its own appropriate base (its parent, or the merge base with the
  pinned base branch — whichever matches what the user asked; ask if
  ambiguous). Don't blindly reuse the current `gh pr diff`. If the
  historical objects aren't fetchable, say so and mark the review partial.
- If the user says the PR is part of a stack and asks for the stack: map it
  (links in the PR body, or the stacked-pr skill), pin and diff each PR the
  same way, and for every finding state whether it belongs to this PR's
  local delta or is inherited from a lower PR.

### Re-reviews

If this is a re-review (the user already got a review earlier in this
conversation, or asks "did anything change" / "is there a new commit"):
compare the current commit list against the last one you looked at. If
there's a new commit, `gh api repos/<owner>/<repo>/commits/<sha> --jq
'.files[] | .patch'` to see just that commit's delta, and report explicitly
which of your prior findings it fixes vs. leaves open — don't just re-review
from scratch and silently drop the thread. When a fix touches code your
earlier findings depended on, re-review the whole affected flow, not only
the delta.

## 2. Read the full discussion first

Pull everything — inline comments, reviews, and general (issue) comments —
with pagination, before writing anything, so you don't repeat settled points
or re-litigate something the author already answered:

```
gh api repos/<owner>/<repo>/pulls/<number>/comments --paginate --jq '.[] | .user.login + " | " + .path + ":" + (.line|tostring) + " | id=" + (.id|tostring) + "\n" + .body + "\n---"'
gh api repos/<owner>/<repo>/pulls/<number>/reviews --paginate --jq '.[] | .user.login + " | " + .state + "\n" + .body'
gh api repos/<owner>/<repo>/issues/<number>/comments --paginate --jq '.[] | .user.login + "\n" + .body + "\n---"'
```

Classify every prior point as **fixed**, **accepted** (author explained,
reviewer satisfied), **deferred**, or **unresolved**. A reply is not proof:
verify "fixed" claims against the code at the pinned SHA, and check
explanations/justifications against the actual code too before accepting
them — an authoritative-sounding reply can still be wrong. Note settled
points as settled instead of re-raising them as fresh findings.

## 3. Read conventions, then trace each changed behavior end to end

Before hunting for findings:

- Read the repo's AGENTS.md / CLAUDE.md (root and affected directories) and
  the nearby files for local conventions — hold the diff to those, not to a
  generic textbook version.
- For **each behavior the diff changes**, trace the full path proactively —
  not only after a candidate finding pops up: input/validation →
  transformation → persistence → external side effects (HTTP, messaging,
  files) → outputs → consumers. Most real bugs show up as a break in that
  chain.
- For a full-stack review, trace the **assembled** flow (all PRs in the
  stack combined) the same way, then attribute each observation to the
  specific PR delta that introduced it.

## 4. Review passes

Run each pass over the traced flows. The passes are coverage dimensions,
not a severity order — severity is assigned per finding (see output format).

1. **Naming, call sites & types** — a dedicated pass, not folded into
   general reading. Names encode meaning, scope, and mutation; flag
   mismatches with their concrete consequence, e.g. a `saveX()` that
   actually replaces the whole collection (callers may assume upsert), a
   name suggesting an allowed-day set when the values really define window
   bounds (readers may test membership where they should check a range), a
   nested passive entry DTO named `XCommand` even though it represents no
   independent operation (command objects can be passive data — the problem
   is implying an operation that isn't there, not mutation), or a tuple that
   quietly grew positional fields with distinct responsibilities and should
   now be a named result model. Check
   every call site of a changed signature is updated, and that types line up
   across layer boundaries (no silent `Any`/raw map where a named model
   belongs).
2. **Correctness & scenarios** — derive the relevant edge cases from the
   traced flow: null/empty/duplicate/partial/stale data, boundary values,
   retries and idempotency, concurrency, partial side effects (what state is
   left behind when step 2 of 3 fails). For each relevant scenario, write it
   up as **expected → actual → consequence** (what should happen, what the
   code actually does, what breaks downstream) — a bare checklist mention
   ("might fail on null") is not a finding. Verify assumptions against the
   actual upstream code or DB schema, not the PR description.
3. **Architecture** — per the project's own rules (e.g. hexagonal: domain
   layer stays framework-free, ports vs. adapters aren't crossed without
   reason, application services orchestrate rather than contain business
   logic, adapters don't leak infra exceptions as domain-meaningful ones).
   Use the project's exact layer names from its AGENTS.md/CLAUDE.md.
4. **Tests** — coverage exercises what it claims to; wiring tests use
   distinguishing non-default values asserted downstream (a test that passes
   with swapped or missing wiring proves nothing); raw/source values are
   preserved where derived ones are computed (no silent overwrite of the
   original). For deleted tests, check whether the behavior is covered
   elsewhere or the feature was intentionally removed — flag the deletion
   only when neither holds.
5. **Code quality & anything else** — duplication, unnecessary abstraction;
   comment hygiene (flag comments a better name or smaller well-named
   functions would make redundant; keep comments that encode non-obvious
   invariants, workarounds for other systems' quirks, fixture/setup context,
   or business rules the code structure alone can't express); PR/stack-
   relative framing in anything that outlives the PR (spec docs, ADRs,
   READMEs, code comments — once merged, the PR is gone from the reader's
   context, so they should read fine cold and point at the ticket instead);
   performance (N+1, full-row fetches where an EXISTS would do); security
   (injection, secret handling); scope creep (unrelated changes bundled into
   a feature PR).

If the user has told you in this conversation to let a specific class of
finding pass ("letting X go", "don't flag Y"), don't re-raise it on a
re-review unless the underlying thing materially changed.

## 5. Verify findings against the live repo, not just the diff

The diff shows what changed, not whether the change is correct. For every
candidate finding, check it against actual state at the pinned SHAs before
writing it up:

- **Line numbers**: diff-relative line numbers lie once a file has more than
  one hunk. Pull the real file at the pinned head commit and count from
  that, or reconstruct hunks precisely — don't eyeball unified-diff line
  numbers. The quoted contents call from section 1 gets you the real file.
- **"Is this dead code?"** — grep the whole repo (not just the diff) for
  callers before flagging something as unused.
- **"Does this constraint/config still exist?"** — read the actual current
  file (migration, port interface, config), don't assume from the PR
  description.
- **"Is this actually N+1 / a hot path?"** — grep for call sites to see if
  it's invoked once per request or in a loop before calling it a performance
  problem. State what you found, not what you assume.
- Trace a continuous flow directly. Delegate only a substantial independent
  investigation when the current harness and task permit it.

Findings that don't survive this check get dropped or downgraded, not
included for effect.

## 6. Output format

Start with **How this works**: the problem the PR solves, the main flow, and
what changes compared with the base revision. For a stack, explain the assembled
behavior before attributing findings to individual PRs. Use a small diagram when
it makes the flow easier to follow; do not turn the overview into a file list.

For each finding:

```
**N. <short title>** — <blocker | should-fix | nit | question>
`<file path>:<real line number>`
\`\`\`
<copy-pasteable comment text — see tone section>
\`\`\`

**Why this matters**
<context → step-by-step behavior → concrete expected-versus-actual example →
consequence → direction of a fix, in plain language>
```

The explanation is for the user, not part of the pasteable comment. Include it
for every finding without waiting for a follow-up request. Define unfamiliar
terms briefly, and use a small code snippet or diagram where it clarifies the
mechanism. Scale the length to the point: a naming nit needs less than a race
condition. Distinguish an implemented bug from a design gap, open question or
preference. Never label the explanation by the reader's seniority.

The label is per finding, so a review that only surfaces naming nits or
genuine questions doesn't force a request-changes verdict. Group
settled-by-discussion items separately from still-open ones. If this is a
re-review, lead with a one-line "what changed since last time" summary
before the finding list.

For a substantial review, also produce the local HTML explanation described in
the shared communication policy, under a stable `pr-<number>` topic for that
repository. Include the PR URL, pinned revision, overview, each finding and its
explanation, verdict and coverage gaps. Keep pasteable comments distinct from
explanations there too. Open the file once unless the user says not to.
Never upload it or include credentials/unnecessary production data. A small
re-review delta can stay in chat with the existing artifact path; do not create
another tab just to confirm a fix. A clean review still gets a brief behavior
overview, not invented findings.

## 7. Tone for the comment text

Match Avanindra's own review-comment voice, not a generic formal reviewer's.
Real examples from his PR history, to calibrate register:

- `sweet`
- `nice, way cleaner`
- `is okay, not sure if I like the changed function signature, could have been an object`
- `Not sure I agree 100%, this is to just verify if the save has worked as expected, but lemme chew on it and I might come around.`
- `Hmmm, keeping it nullable read better but this also works`

Takeaways:
- Short. A sentence or two, no preamble.
- Direct opinions stated plainly ("not sure I agree", "is okay but") — not
  hedged corporate phrasing.
- Contractions, casual connectors ("but", "though", "lemme").
- A short positive reaction is a complete comment on its own — don't
  manufacture a nitpick to pad it out, and match the reaction to genuine
  weight ("nice" for a good renaming, not for a one-line import cleanup).
- Ask genuine questions when you want their input, not to disguise an
  instruction.
- No formal risk framing ("As-is it'll bubble up as an unhandled 500") — say
  it the way he would: "this'll blow up with a bare 500 if the planning
  group's gone, worth a proper exception here?"
- Still include the substance (what's wrong, what could happen) — tone
  changes the wrapping, not the content.

## 8. Final verdict

Close with an explicit call, one of: **Approve**, **Request changes**, or
**Comment only** — plus one or two sentences of reasoning (what would need
to change to flip an Approve, or why what's open isn't blocking). Base it on
severity, not count — one correctness bug outweighs five style nits.

Add a short **coverage & gaps** note: what you actually checked (pinned SHA,
passes run, flows traced) and what you did **not** verify (e.g. no local
build, migration not run, downstream consumer repo not checked). Never claim
a check you didn't perform — and don't give **Approve** while material gaps
stay unverified; use **Comment only** and name what's missing instead.
