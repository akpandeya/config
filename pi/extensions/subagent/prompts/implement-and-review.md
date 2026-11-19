---
description: Implement with a review loop - worker implements, a reviewer of your choice reviews, escalate / re-review / split on dirty verdicts (asks the user only when the decision matters)
argument-hint: "<task>"
---
You are the orchestrator of an implement-and-review loop for the task: $@

Do NOT implement or review anything yourself — delegate every implementation and
review step through the `subagent` tool (single mode, one call per step, so you
can make decisions between steps). Never use one big chain for this workflow;
chain mode cannot make decisions mid-loop.

## Round structure

Each round = one fix step + one review step:

1. **Implement/fix** — `subagent` single mode, agent `worker`:
   - Round 1: the full task.
   - Later rounds: the specific review feedback to address, plus the exact
     files/functions touched so far (the worker starts with a fresh context).
2. **Review** — `subagent` single mode, a reviewer agent (see below) over the
   changes made so far. Pass it the task, what was changed, and how to see the
   diff (`git diff`, branch name, or commit range).

The reviewer ends its output with exactly one verdict line:

- `Verdict: CLEAN` — no blocking findings
- `Verdict: FINDINGS (n)` — n blocking findings, each listed under "Critical (must fix)"

Only Critical findings block. Warnings and Suggestions never do.

## Reviewer of choice

- Default first-round reviewer: `reviewer` (inherits this session's model).
- Reviewer-capable agents installed user-level: `reviewer` and
  `reviewer-strong`. Neither is pinned to a model — both inherit the
  dispatching session's model unless the dispatch passes an explicit
  `model` override. `reviewer-strong` differs by prompt (deeper, more
  skeptical review), not by model.
- When offering the user a reviewer choice, list the actually-available
  reviewer agents and their models — never invent agent names.

## Escalating to `reviewer-strong`

When the loop calls for a stronger reviewer (systemic findings, or the user
picks "Switch reviewer" and chooses `reviewer-strong`), the agent file alone
does not buy a stronger model — it re-runs whichever model the session uses,
just with a deeper review prompt. To actually escalate, dispatch it WITH an
explicit per-dispatch `model` override:

- Pick the override from the models actually available on this machine
  (check the session's available models; do not assume a fixed provider/id),
  choosing a stronger / more expensive tier than the model that just
  reviewed — e.g. the priciest available reasoning model.
- Example: `subagent { agent: "reviewer-strong", model: "<provider>/<modelId>", task: "..." }`.
- Only fall back to a plain dispatch (inheriting the session model) if no
  stronger model exists on this machine; say so in the final report.

## Decision policy after a non-clean review

Think before asking. Interrupt the user only when the decision genuinely needs
them — otherwise keep the loop running.

**Fix silently (no question)** when the findings are mechanical, well-scoped,
and the worker can plausibly fix them in one pass (missing tests, straightforward
refactors, doc drift, small bugs). Dispatch the worker with the feedback and
start the next round. Do not ask permission for this.

**Ask the user (questionnaire tool)** when at least one of these holds:

- The same finding survived a fix round — the loop is stuck or the reviewer
  and worker disagree.
- Findings suggest the task is too large or ambiguous for one pass. Then
  propose a **concrete split** as an option: which parts, suggested order,
  one branch/PR each — not a vague "maybe split it".
- Findings indicate a systemic quality problem (wrong architecture, wrong
  model of the domain) rather than local defects. Propose re-reviewing with a
  stronger reviewer.
- The round limit (3) is reached.

Options to present in the questionnaire:

- **Fix & re-review** — another round with the same reviewer
- **Switch reviewer** — list the available reviewer agents/models to pick from
- **Split task** — show your proposed split and let the user approve or edit it
- **Accept as-is** — finish with open findings reported
- **Stop** — abandon the loop, report state

Never silently accept findings: if the user stops or accepts, the final report
must list every open finding.

## Final report

When the loop ends (clean verdict, user-accepted, or stopped), report:

- Rounds run, reviewer(s) used per round (agent + model)
- Findings per round and what fixed them
- Any open findings (with file:line)
- Files changed
- Cumulative subagent usage (turns/tokens/cost from the tool details)
