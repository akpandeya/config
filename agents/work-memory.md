# Curated work memory

This protocol is active only in the **work** agent profile. The launcher exposes
an employer-approved work-only repository as `~/.agent/profiles/work/memory`.
Never read or write the personal profile's memory. If the work memory link is
absent, continue without long-term memory; do not clone a repository or fall
back to personal storage.

Work memory is deliberately limited to preferences, approved tools and
terminology. Project state, architecture, tickets, code and decisions belong
in repository documentation. Session history is separate and must not be
copied into personal storage.

## Reading

- At the start of a session, read `~/.agent/profiles/work/memory/INDEX.md` plus
  `preferences.md`, `tools.md` and `glossary.md` if they exist.
- If `~/.agent/profiles/work/device.md` exists, use it only for this machine's
  non-secret, work-relevant capabilities. It is local-only and must not be
  committed or synchronized.
- Do not read `~/.agent/profiles/personal/memory` or the external personal memory
  repository.

## Layout

```
~/.agent/profiles/work/memory -> employer-approved work-only repository
├── INDEX.md
├── preferences.md   # work-specific response and workflow preferences
├── tools.md         # approved tools and when the user chooses them
└── glossary.md      # internal acronyms and terminology
```

Do not add `people/`, `areas/` or general `topics/` files without changing
this policy deliberately.

## Writing

- Write only when the user explicitly asks to remember or update a work
  preference, tool choice or glossary entry. There is no automatic
  whole-conversation consolidation.
- Follow the [stated] test: record only what the user said, without inference,
  hearsay, assistant suggestions or tool/search results.
- Treat internal acronyms, team terminology and employer-specific tool choices
  as work-only, even when they appear harmless. Public industry terms normally
  do not need memory because they can be looked up again.
- Keep entries narrow: "For work, prefer tool X for workflow Y" rather than a
  general preference for X everywhere.
- Do not record project status, architecture, ticket details, source code,
  credentials, customer data, internal URLs or other confidential material
  beyond the approved glossary/tooling terminology.
- Never consolidate a work conversation into personal or shared memory.
  Promotion of a genuinely generic preference requires a separate manual
  review in the personal config repository.

## Device and offboarding

Device notes stay in the local work profile and contain no credentials,
internal hostnames, project state or environment details. Work memory and work
sessions remain employer-owned; do not export them to personal storage when
the work arrangement ends.

This protocol provides accident-resistant separation, not a hard OS-level
security boundary.
