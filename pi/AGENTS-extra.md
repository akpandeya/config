## Jira tickets

For Jira tickets, use the `jira` CLI (e.g. `jira view TGH-xxxx`) to fetch
summary/acceptance criteria before planning; it is allowlisted in plan mode
(read-only subcommands: view, list, issue view/list, board, sprint, comment list).

## Ticket-driven work

When the user asks to work on a ticket or issue ("work on TGH-123", "fix gh
issue #45", "pick up that story"), load the `pick-up-issue` skill first: it
resolves the ticket via `jira`/`gh`, judges whether the body is a complete
task spec, and either implements it directly or routes to the decomposition
pipeline. The explicit entry point is `/pick-up-ticket <number|KEY>` (Claude
Code `/pick-up-ticket`, pi `/pick-up-ticket` prompt template).
