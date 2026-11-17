---
description: Fix the non-blocking reviewer nits from the plan-mode review-skip commit (914faae)
---
Fix the review nits below in the plan-mode extension, then run the test suite
and commit. Keep the changes minimal — these are polish fixes, not refactors.

Nits to fix (from the reviewer pass on 914faae):

1. `pi/extensions/plan-mode/index.ts` (~lines 543-547, the `why` chain inside
   `beginReview`): when the user manually picks the unstarred "⏭ Skip review"
   on the FIRST round (no planner annotation, trivial heuristic did not fire),
   the `plan-review-skipped` card currently reads "trivial/mechanical plan",
   which is false. Branch order should distinguish a manual first-round skip:
   `!firstRound → "manual bail-out after a changes-requested round"`,
   `!suggestSkip → "manually skipped"`, `plannerReviewSkip → planner-suggested`,
   else "trivial/mechanical plan". (suggestion tier, optional: also mention
   headless auto-skip in the planner prompt clause about the review dialog.)

2. `pi/extensions/plan-mode/utils.ts` (~lines 294-296): the regex comment sits
   inside the `return { ... }` object literal as two dangling `//` lines.
   Move the comment above the `return` statement (or restructure cleanly).

Do NOT change behavior beyond nit 1's label wording. Do not persist
`plannerReviewSkip` (the reviewer considered it, left it out intentionally —
consistent with `lastImplementerPick`).

Verify: `python3 -m unittest scripts.tests.test_pi_extensions` must pass
(30 tests), and `pi --help | grep -- --plan` must still succeed (extension
loads). Commit as one commit:
`fix(pi): correct the skip-card reason for manual first-round skips + tidy parser comment`
