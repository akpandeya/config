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
gh pr view <target> --json url,title,body,author,baseRefName,headRefName,state,additions,deletions,changedFiles,labels,baseRefOid,headRefOid
gh pr view <target> --json commits -q '.commits[] | .oid[0:8] + "  " + .committedDate + "  " + .messageHeadline'
gh api "repos/<owner>/<repo>/compare/<baseRefOid>...<headRefOid>" --jq .merge_base_commit.sha
```

- Use the pinned SHAs everywhere — never moving branch names. The review
  base is the **merge base** of the pinned base and head commits (the
  compare call above), not the base-branch tip.
- Get the diff between the pinned merge base and pinned head with
  `git diff <merge_base> <head_sha>` when the exact objects are already
  available, or the pinned API equivalent
  `gh api "repos/<owner>/<repo>/compare/<merge_base>...<head_sha>"`. Never
  substitute a current `gh pr diff` — it follows moving branch tips and is
  wrong for a pinned or historical review. The compare API truncates large
  file patches — if a changed file shows no visible patch or the diff looks
  cut off, use a disposable clone outside the reviewed checkout for the
  complete local diff. Do not fetch, check out or otherwise mutate the
  reviewed repository merely to obtain review evidence.
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
  local delta or is inherited from a lower PR. The PR whose local delta
  introduced the problem owns the finding's comment location, even when
  the problem was discovered in the assembled stack. Do not default to the
  top PR; retain each owning PR's URL, pinned head and merge base.

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

## 5. Verify findings at pinned revisions, then generate PR navigation

The diff shows what changed, not whether the change is correct. For every
candidate finding, check it against actual state at the pinned SHAs before
writing it up:

- **Line numbers**: diff-relative line numbers lie once a file has more than
  one hunk. Pull the real file at the pinned head for RIGHT/new lines, or
  the pinned diff base for LEFT/deleted lines, and count from that, or
  reconstruct hunks precisely — don't eyeball unified-diff line numbers.
  Use the old path for deleted lines in renamed files. The quoted contents
  call from section 1 gets you the real file; use the base SHA for old-side
  evidence.
- **"Is this dead code?"** — grep the whole repo (not just the diff) for
  callers before flagging something as unused.
- **"Does this constraint/config still exist?"** — read the actual file at
  the pinned revision (migration, port interface, config), don't assume
  from the PR description.
- **"Is this actually N+1 / a hot path?"** — grep for call sites to see if
  it's invoked once per request or in a loop before calling it a performance
  problem. State what you found, not what you assume.
- Trace a continuous flow directly. Delegate only a substantial independent
  investigation when the current harness and task permit it.

Findings that don't survive this check get dropped or downgraded, not
included for effect.

### Generate all finding links together

Use the read-only helper after the findings and their owning PRs are known:

```bash
~/.config/agent-context/scripts/pr-comment-links.py \
  --input /tmp/deep-review-pr-123-links.json \
  > /tmp/deep-review-pr-123-links.out.json
```

The request is one batch so PR metadata and complete diffs are read and parsed
once per revision pair:

```json
{
  "repository": "/absolute/path/to/checkout",
  "pr_url": "https://github.com/owner/repo/pull/123",
  "reviewed": {
    "base_tip": "1111111111111111111111111111111111111111",
    "merge_base": "2222222222222222222222222222222222222222",
    "head": "3333333333333333333333333333333333333333"
  },
  "findings": [
    {"id": "finding-1", "path": "src/example.py", "side": "RIGHT", "line": 42},
    {"id": "finding-2", "path": "src/old.py", "side": "LEFT", "line": 17}
  ]
}
```

Use full SHAs and real values. The helper validates the complete request before
emitting results. It rejects malformed or partial input and explicitly reports
missing Git objects, binary targets, submodules, context-line targets, and
unsupported/ambiguous cases rather than guessing. It does not fetch, check out,
write to the reviewed repository, or post to GitHub; make the required commit
objects available before invoking it.

The helper:

- recomputes each merge base from the base tip and head;
- parses the complete merge-base-to-head diff with old/new hunk counters;
- accepts only an added line for `RIGHT` or deleted line for `LEFT` — diff
  positions and context lines are never comment locations;
- keeps old path, new path, diff-anchor path and pinned-source path separate
  for renames and deletions;
- constructs the observed GitHub candidate convention
  `<PR URL>/changes#diff-<SHA256(repository-relative diff path)>R<new-line>`
  or `L<old-line>`;
- creates a separate full-SHA pinned source URL at the reviewed head/new path
  for `RIGHT`, or reviewed merge base/old path for `LEFT`; and
- bounds revision retries if the PR moves during the run, reporting the last
  coherent snapshot instead of looping.

The hash/fragment is a GitHub UI convention, not a guaranteed public API.
Computing it and receiving HTTP 200 for the page do not verify that the
fragment rendered or selected the intended line.

### Preserve reviewed evidence and map the live diff

The original review pins never move. Compare the reviewed effective diff with
the current owning PR's effective diff (current merge base to current head):

- A changed base-branch tip alone is metadata movement. If merge base, head and
  relevant effective diff are unchanged, reuse the cached Git evidence. Prior
  rendered verification may also be retained when the candidate URL and
  validated target fingerprint still match; retain the snapshot where it was
  rendered and record the new live metadata separately.
- If the effective diff changes, revalidate the affected finding. The helper
  maps only one exact hunk-level correspondence, including the target's
  position among surrounding diff lines. Never relocate a finding by matching
  one filename, old line number or isolated line of text.
- If correspondence is absent or ambiguous, the current comment location is
  unavailable. Keep the original pinned evidence and state whether the issue
  appears fixed, historical, or simply unmappable after the change.

For stacked PRs, run the helper against each owning PR and keep every finding
attached to the PR whose local delta introduced it. Do not move a lower-PR
finding to the top PR merely because the assembled stack exposes it.

For closed or merged PRs, retain the PR state as navigation metadata. State
alone does not prove a finding fixed, does not prove its diff unavailable, and
does not convert an historical review conclusion into a current merge
recommendation.

### Verification statuses

Use exactly one status per finding:

- **Rendered-verified** — the actual GitHub Files changed anchor was inspected
  and confirmed to target the exact file, side and changed line at the recorded
  live revisions.
- **Diff-validated, UI-unverified** — Git metadata, effective diff,
  correspondence, path, side and changed line are verified, but the generated
  URL fragment was not inspected in GitHub's rendered UI. This is the default
  successful helper result and is allowed in the report.
- **Unavailable** — ownership, a changed-line target, correspondence, or a
  supported diff could not be established without guessing.

Browser inspection is optional escalation. Use it when the user explicitly
asks for rendered verification or when it can resolve real uncertainty. If it
is unavailable or interrupted, keep the honest Git-only status; do not launch a
long browser workaround. Never claim `Rendered-verified` because a URL was
generated, an HTTP request succeeded, or a comment could theoretically be
submitted. This workflow never submits a comment.

### Two locations per finding

Keep review evidence separate from live navigation. Each finding has a primary
**Comment in PR** link and a separate **Pinned source** link:

1. **Locate the introducing change.** In the owning PR's complete pinned
   local diff, identify the relevant changed line, file path (including any
   rename), hunk and side: RIGHT for an added/new line, LEFT for a deleted/old
   line. Diff positions are not file line numbers. Unchanged supporting code
   is pinned evidence, not a comment location; do not attach a finding to an
   unrelated changed line just to make it commentable.
2. **Pin the evidence.** Link to the exact file and line at the owning PR's
   reviewed head for RIGHT, or its pinned diff base and old path for LEFT,
   using a full commit SHA in a `/blob/<sha>/<path>#L<line>` URL. Keep
   supporting source links pinned too, including assembled-stack evidence
   at the reviewed top head when relevant.
3. **Validate the live target separately.** Use the helper's current snapshot
   and complete effective diff. Do not silently replace reviewed pins with
   live revisions. If the current target exists, use its live path, side and
   line in the candidate link and include the status. If the issue was fixed,
   mark it fixed/historical instead of offering the old target as current.
4. **Escalate rendered verification only when needed.** If the actual rendered
   Files changed target is inspected, record the live base tip, merge base,
   head, helper-provided target fingerprint and exact URL as rendered evidence.
   Recheck revisions once; if they moved, rerun the bounded helper workflow.
   Preserve the rendered status only when the URL and target fingerprint still
   match; otherwise downgrade it.
5. **Fail explicitly, not approximately.** If ownership, the changed line,
   or live-code correspondence cannot be verified,
   show **Comment in PR: unavailable** with the reason, and retain
   **Pinned source**. A generic PR URL, file-only anchor or source permalink
   is not a substitute for a line target. Keep any known owning PR identified.

These are read-only navigation checks, never permission to create a draft,
review or comment. A candidate or rendered-verified comment link belongs to the
recorded live revision; pinned source remains the stable evidence if the PR
later moves.

## 6. Output format

Start with **How this works**: the problem the PR solves, the main flow, and
what changes compared with the base revision. For a stack, explain the assembled
behavior before attributing findings to individual PRs. Use a small diagram when
it makes the flow easier to follow; do not turn the overview into a file list.

For each finding:

```
**N. <short title>** — <blocker | should-fix | nit | question>
[Comment in PR](<owning PR Files changed line URL>) — PR #<owning PR>, `<live path>:<live line>` (<RIGHT | LEFT>) — <Rendered-verified | Diff-validated, UI-unverified>
[Pinned source](<exact pinned file/line URL>) — `<pinned path>:<pinned line>` at `<reviewed SHA>`
\`\`\`
<copy-pasteable comment text — see tone section>
\`\`\`

**Why this matters**
<context → step-by-step behavior → concrete expected-versus-actual example →
consequence → direction of a fix, in plain language>
```

Keep **Comment in PR** first: it is the finding's primary location in both chat
and HTML. When unverified, replace only that link with
`Comment in PR: unavailable — <reason>`; keep the separately labelled pinned
source link and any known owning PR. `Diff-validated, UI-unverified` is a valid
linked state, not "unverified" for this unavailable rule. Do not turn supporting
unchanged code into a purported comment target.

The explanation is for the user, not part of the pasteable comment. Include it
for every finding without waiting for a follow-up request. Define unfamiliar
terms briefly, and use a small code snippet or diagram where it clarifies the
mechanism. Scale the length to the point: a naming nit needs less than a race
condition. Distinguish an implemented bug from a design gap, open question or
preference. Never label the explanation by the reader's seniority. Do not
present a proposed fix or intended behavior as already implemented.

The label is per finding, so a review that only surfaces naming nits or
genuine questions doesn't force a request-changes verdict. Group
settled-by-discussion items separately from still-open ones. If this is a
re-review, lead with a one-line "what changed since last time" summary
before the finding list.

For a substantial review, also produce the local HTML explanation described in
the shared communication policy, under a stable `pr-<number>` topic for that
repository. Use the review template below for the input JSON so every review
artifact has the same shape. Include the PR URL, pinned revision, overview,
each finding and its explanation, verdict and coverage gaps. Keep pasteable
comments distinct from explanations there too: put each finding's
copy-pasteable text in a direct `comments` block (the renderer shows it as a
copy-to-clipboard block), never inside the explanation or expandable evidence.

Choose blocks for the explanation rather than filling every available type:

- Use a `comparison` when the important point is expected versus actual,
  before versus after, or another concrete difference.
- Use a Mermaid `diagram` when relationships, interactions, ordering, branches
  or state transitions are easier to see than reconstruct from prose.
- Use a short `text` block as a worked example when the reader needs to follow
  one concrete input through the behavior.
- Use `details` for source traces and secondary evidence that would interrupt
  the main explanation. Keep the conclusion, consequence, coverage boundary
  and other information required to understand the finding visible.

A simple finding can remain one short text block plus its comment. A diagram
must reduce reading work rather than repeat nearby prose or inflate a small
finding. Every diagram needs a useful caption and a text alternative that
explains the relationship without relying on the picture.

Make every reference clickable: give pinned SHAs as full commit or compare URLs
(metadata values accept `{"text": "...", "url": "https://..."}`, and bare
https URLs in text blocks are auto-linked), and list all stacked PRs and key
files under `sources`. Every `Finding ...` section carries a `severity` (blocker |
should-fix | nit | question — rendered as a colored badge) and a `location`:
use `{"text": "Comment in PR: ... - Diff-validated, UI-unverified", "url":
"https://..."}` for a generated candidate, or the same shape with
`Rendered-verified` after actual UI inspection. Include the PR, path, live line
and side in the text. Put `Pinned source: ...` and its bare HTTPS file/line URL
in the finding's visible explanation or expandable evidence, and add a labelled
entry under `sources`; it is evidence, not a replacement for the primary
comment location. Put the recorded live snapshot and what was actually verified
in `metadata` or a text block. For an unavailable target, use a plain-text `location` such as
`Comment in PR: unavailable - live diff correspondence was ambiguous`; retain
the pinned evidence, sources and pasteable comment. Do not invent
`comment_url`/`side`/`verification_status` fields; keep navigation in
`location`, evidence in content blocks and the source list.
Text is plain text with auto-linked URLs, not Markdown links.
Section order is fixed as in the template; the headings of the non-finding
sections are free text — the
renderer only requires the `Finding` prefix on finding sections and one heading
containing `Verdict`. Leftover `<sha>`/`<number>`/`<owner>`/`<repo>`
placeholders in fill-in slots (summary, headings, metadata, location, sources)
fail the render, so fill every placeholder — quoting them inside paragraphs,
code or comments is fine. The `Reviewed`
metadata key is optional — the renderer stamps the UTC generation time itself.
Open the file once unless the user says not to. Never upload it or
include credentials/unnecessary production data. A small re-review delta can
stay in chat with the existing artifact path; do not create another tab just to
confirm a fix. A clean review still gets a brief behavior overview, not invented
findings.

Review template for the artifact input JSON (sections in this order). The
`path/to/file.ext` path and its diff anchor below are illustrative, not a
verified PR location. Replace the entire location URL with the verified
owning-PR line permalink; do not reuse the sample anchor. This example uses
RIGHT/head evidence; for LEFT use the pinned base and old path in the source
links. Fill live and pinned line numbers separately if they differ.

```json
{
  "kind": "review",
  "title": "Deep review: <PR title or stack subject>",
  "summary": "One paragraph: verdict-flavored overview for someone who reads nothing else.",
  "sections": [
    {"heading": "What changed since last review",
     "blocks": [
       {"type": "text",
        "text": "re-reviews only: new commits since the previous review, which prior findings they fix or leave open"}
     ]},
    {"heading": "How this works (assembled stack)",
     "blocks": [
       {"type": "text", "text": "problem + main flow, stack-relative if stacked"},
       {"type": "diagram",
        "source": "flowchart LR\n  A[Input] --> B[Changed behavior]\n  B --> C[Downstream outcome]",
        "caption": "The changed behavior connects the input to its downstream outcome.",
        "text_alt": "Input reaches the changed behavior, which produces the downstream outcome."}
     ]},
    {"heading": "Prior findings and concerns - status",
     "blocks": [
       {"type": "text",
        "text": "per prior point: fixed / accepted / deferred / unresolved, with evidence"}
     ]},
    {"heading": "Finding N (severity, PR): short title",
     "severity": "blocker | should-fix | nit | question",
     "location": {"text": "Comment in PR: #<number> - path/to/file.ext:<line> (RIGHT) - Diff-validated, UI-unverified",
                  "url": "https://github.com/<owner>/<repo>/pull/<number>/changes#diff-67d508e772e0496a6cd4e7c39fbe3e5658c6efbd8343abf45b2ccdbf962c1ce3R<line>"},
     "blocks": [
       {"type": "callout",
        "title": "Rule or consequence that matters",
        "text": "State the key invariant, assumption or user-visible consequence."},
       {"type": "text",
        "text": "Verification: Git merge base, complete diff, hunk, path, RIGHT line and reviewed-to-live correspondence were checked; the rendered GitHub fragment was not inspected."},
       {"type": "comparison",
        "left": {"label": "Expected", "value": "required outcome",
                 "text": "What should happen for one concrete input."},
        "right": {"label": "Reviewed behavior", "value": "observed outcome",
                  "text": "What the pinned code does and what changes downstream."},
        "caption": "State whether this is a verified implementation bug, design gap, assumption or open question."},
       {"type": "text",
        "text": "Consequence and fix direction. Describe required behavior as a proposal unless the reviewed code already implements it."},
       {"type": "details",
        "summary": "Evidence and pinned source",
        "blocks": [
          {"type": "text",
           "text": "Pinned source: path/to/file.ext:<line> at reviewed head - https://github.com/<owner>/<repo>/blob/<head>/path/to/file.ext#L<line>"},
          {"type": "steps",
           "items": ["source-trace step", "next verified step", "downstream effect or coverage boundary"]}
        ]},
       {"type": "comments", "items": ["exactly the copy-pasteable comment text"]}
     ]},
    {"heading": "Verified claims (checked, not assumed)",
     "blocks": [
       {"type": "text",
        "text": "what was verified against the pinned SHAs; settled points not re-raised"}
     ]},
    {"heading": "Verdict and coverage",
     "blocks": [
       {"type": "text",
        "text": "the explicit verdict + one or two sentences; what was checked, what was not"}
     ]}
  ],
  "metadata": {
    "PR": {"text": "#<number>", "url": "https://github.com/<owner>/<repo>/pull/<number>"},
    "PR state": "open",
    "Pinned revisions": {"text": "base <sha>...head <sha>",
                         "url": "https://github.com/<owner>/<repo>/compare/<base>...<head>"},
    "Navigation snapshot": "live merge base <base>, head <head>; diff validated, rendered UI not inspected"
  },
  "sources": [
    {"label": "PR #<number> (<what>)", "url": "https://github.com/<owner>/<repo>/pull/<number>"},
    {"label": "Finding N - Pinned source: path/to/file.ext:<line> (reviewed head)",
     "url": "https://github.com/<owner>/<repo>/blob/<head>/path/to/file.ext#L<line>"}
  ]
}
```

Omit the leading "What changed since last review" section for a first review.
For a stack, one "Finding N" section per finding with the owning PR in the
heading and its own verified PR comment location, even for a lower PR.
Each finding's source links use that finding's pinned evidence revision, not
automatically the top head; metadata's compare URL still spans the whole
stack's merge base to top head. Replace the single-PR placeholders per finding,
and list all stack PRs and pinned supporting files under `sources`.
Dark mode is automatic (the page follows the system theme); no toggle needed.

### Refreshing artifact links

Treat "refresh the artifact links" as navigation maintenance, not a new review:

- preserve findings, severity, pasteable comments, explanations and all
  reviewed evidence pins;
- update only PR state, current snapshot, comment-link target and verification
  status;
- revalidate only findings whose effective diff changed; and
- say explicitly that no fresh full review, test run or discussion sweep was
  performed.

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
