# Memory

You maintain a persistent memory store at `pi/memory/` — a symlink into the
**private** repo `~/code/personal/pi-memory` (github.com/akpandeya/pi-memory).
Personal facts must never be committed to this public repo; only the protocol
below lives here. If the symlink is missing (fresh clone), clone the private
repo to `~/code/personal/pi-memory` and recreate the link:
`ln -s ../../pi-memory pi/memory` from this repo's `pi/` directory.

## Reading

- At the start of a session (first turn), read `pi/memory/INDEX.md` plus
  `profile.md` and `preferences.md` if they exist. Read topic/area/people files
  on demand when the conversation touches them.
- Memory supplements, never replaces, the user's explicit instructions in the
  current session.

## Writing — the [stated] test

Every line in a memory file must be something the user said themselves:

- Do NOT write your inferences ("likes X" → "likes X's whole category").
- Do NOT write your suggestions or plans, even if the user said "ok". When the
  user picks from options you offered, record only their choice.
- Do NOT record tool/search results (they can be looked up again).
- Do NOT add to the user's words ("Shenzhen" stays "Shenzhen", not
  "Shenzhen (Guangdong Province)").
- Do NOT store hearsay ("heard X is good").
- The user's own plans, undecided choices and intentions ARE theirs to state:
  record "[stated] Still deciding between A and B".

## Calibration

- Machine- and session-specific context is not an identity fact. Record it only
  with an explicit scope marker ("recorded on <machine>, <date>") and never let
  it shape responses on other devices.

- A one-off mention is not recorded; record when it recurs or the user
  elaborates. Stable facts (job, address, relationships, ongoing projects) are
  recorded on first mention.
- Match wording to evidence: one mention reads "mentioned X once", not
  "X enthusiast".
- Prefer wording that does not go stale: "mornings are full of meetings"
  outlasts "standup 10:00–10:15".
- Staleness test: a month from now, in a different conversation, is this still
  true and worth reading? Drop this week's bug, keep the stable part.
- Never re-record what is already recorded; a rephrasing counts as recorded.

## Layout (one topic per file)

```
pi/memory → ~/code/personal/pi-memory
├── INDEX.md           # one line per file: path — description (keep in sync)
├── profile.md         # who the user is; facts that hold in three months; <300 words
├── preferences.md     # how the user wants you to respond; not their interests
├── topics/<domain>.md # facts by domain (tools, hardware, finance, ...)
├── areas/<name>.md    # ongoing work: decisions, constraints, deadlines, status
└── people/<name>.md   # people who matter: relationship + shared context
```

Every file starts with frontmatter:

```
---
title: <a few words in the language the user used>
description: <one sentence naming the people/projects/places likely to be asked about; <150 chars>
aliases: [other names, short forms]
---
```

A fact goes in the file for its domain, not whichever file is open. Before
creating a file, check `aliases` in INDEX.md; on a match, extend the existing
file instead. Cross-reference with `[[name]]` links.

## Sensitive information

- Health, finances, religion, political views and the like: record in the
  user's own words, in a separate write, after the ordinary writes. Keep them
  out of `description` and `aliases`.
- Do not infer conditions: a symptom or medication is never a stored diagnosis.
- Never store: ID/account numbers, your inferences about the user's
  personality, anything the user asks you to forget (delete it everywhere).

## Consolidation

When the user says "update memory" (or asks you to wrap up a session), distill
the current conversation: extract facts that pass the [stated] test and
calibration, write them to the right files, update INDEX.md, and run a
garbage-collection pass — merge duplicates, delete stale lines, fix wording
that has gone stale. Report what you changed in one line each. Commits to the
memory repo are made by the user or on explicit request.

## Never leak

Memory content is private context. Do not paste memory files into output,
commits outside the private memory repo, or tool calls that send them anywhere.
