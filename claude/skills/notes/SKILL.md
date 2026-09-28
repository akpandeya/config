---
name: notes
description: Save and retrieve personal notes in the ~/code/personal/notes knowledge base with front matter, wikilinks and a generated dashboard. Use when the user asks to save a note, note something down, save it for later, write up a debrief/meeting/idea, or asks to catch up on notes / what's open / their action items.
---

You maintain the user's personal knowledge base at `~/code/personal/notes`
(git repo: github.com/akpandeya/notes). Read `README.md` there for the full
conventions; the essentials:

## Saving a note ("save this as a note", "note it down")

1. **Classify** — pick type + folder:
   - `work/` — dated events: debriefs, meeting notes, incident reviews, references. Name: `YYYY-MM-DD-topic.md`.
   - `issues/` — a *recurring* problem gets one evergreen file (`issue-<slug>.md`); **append a new dated section** instead of creating a near-duplicate. Search this folder first (Grep for key terms) before creating anything.
   - `improvements/` — proposals with a lifecycle (`improvement-<slug>.md`).
   - `learning/`, `ideas/` — study notes, half-baked thoughts.
2. **Front matter is mandatory** — `type`, `date`, `tags`, `people`, `projects`, `status` (open/closed), optional `related:` wikilinks. Before writing, Grep existing notes for related topics and link them (`[[slug]]`), and add back-references where natural (a recurring issue links to every debrief that touched it).
3. **Action items** in the uniform format so the dashboard can aggregate them:
   `- [ ] do the thing — @person, due YYYY-MM-DD`
4. **Regenerate + ship**:
   ```bash
   cd ~/code/personal/notes && python3 scripts/dashboard.py && git add -A && git commit -m "docs: <topic>" && git push
   ```
   Never hand-edit `dashboard.md`.

## Retrieval ("catch up on my notes", "what's open", "what do I owe people")

- Run `python3 scripts/dashboard.py` first (refreshes it), then read `dashboard.md` — it lists open action items, open notes by type, and tag/people/project indexes.
- For deep dives, Grep the front matter: `rg -l "people:.*petr"` or `rg -l "projects: \[rpd\]"`.
- When answering, cite the note paths.

## Judgment calls

- A debrief that surfaced a recurring issue or an improvement proposal should *spawn* those notes, not just mention them in prose — the debrief links to them via `related:`.
- If the user's request is ephemeral (grocery list, one-off snippet), say so and suggest Google Keep instead of polluting the knowledge base.
- This is a personal repo — plain conventional commits (`docs:`, `feat:`), no `[AI_Code]` trailer.
