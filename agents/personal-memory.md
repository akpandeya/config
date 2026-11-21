# Personal memory

This protocol is active only in the **personal** agent profile. The launcher
exposes the external private personal repository as
`~/.agent/profiles/personal/memory`. Never read or write the work profile's memory,
and never copy work content into this store. If the memory link is absent,
continue without memory and ask the user to set up the personal repository;
do not clone it during a session.

The shared core is limited to the generic communication and tool preferences
already present in the common instructions. Interests, identity, personal
projects and plans belong only here. Shared additions require a separate,
manually reviewed config change.

## Reading

- At the start of a session (first turn), read
  `~/.agent/profiles/personal/memory/INDEX.md` plus `profile.md` and
  `preferences.md` if they exist. Read topic/area/people files on demand when
  the conversation touches them.
- If `~/.agent/profiles/personal/device.md` exists, use it only for this machine's
  non-secret capabilities and preferences. It is local-only and must not be
  committed or synchronized.
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

- A one-off mention is not recorded; record when it recurs or the user
  elaborates. Stable facts (address, relationships, ongoing personal projects)
  are recorded on first mention.
- Match wording to evidence: one mention reads "mentioned X once", not
  "X enthusiast".
- Prefer wording that does not go stale: "mornings are full of meetings"
  outlasts "standup 10:00–10:15".
- Staleness test: a month from now, in a different conversation, is this still
  true and worth reading? Drop this week's bug, keep the stable part.
- Never re-record what is already recorded; a rephrasing counts as recorded.
- Machine- and session-specific context belongs in the local `device.md`, not
  in identity, preference or topic files.

## Layout (one topic per file)

```
~/.agent/profiles/personal/memory -> external private personal repository
├── INDEX.md           # one line per file: path — description (keep in sync)
├── profile.md         # stable personal facts; <300 words
├── preferences.md     # personal response preferences; not interests
├── topics/<domain>.md # personal interests and facts by domain
├── areas/<name>.md    # personal projects, decisions and status
└── people/<name>.md   # personal relationships and shared context
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
- Never store: ID/account numbers, credentials, employer-confidential
  information, your inferences about the user's personality, or anything the
  user asks you to forget (delete it everywhere).

## Consolidation

When the user says "update memory" (or asks you to wrap up a personal
session), distill the current conversation: extract facts that pass the
[stated] test and calibration, write them to the right files, update INDEX.md,
and garbage-collect duplicates and stale wording. Report what you changed in
one line each. Commits to the memory repo are made by the user or on explicit
request. Never run this consolidation against a work session.

## Never leak

Memory content is private context. Do not paste memory files into output,
commits outside the private memory repo, or tool calls that send them
anywhere. This protocol provides accident-resistant separation, not a hard
OS-level security boundary.
