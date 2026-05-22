---
name: snowflake-query
description: Run a SQL query against HelloFresh Snowflake using the `snow` CLI under the user's SSO identity. Use when the user asks to run a query, execute a `.sql` file, or fetch data from Snowflake.
allowed-tools: Bash, Read, Write
---

You're running SQL against HelloFresh Snowflake on the user's behalf via the `snow` CLI. The `hf` connection is already configured (externalbrowser SSO, defaults: role `US_OPS_ANALYTICS_ENGINEER_NONSENSITIVE`, warehouse `US_OPS_ANALYTICS_DEV`, database `US_OPS_ANALYTICS`).

## Running queries

**Inline query:**
```bash
snow sql -c hf -q "SELECT ..."
```

**From a `.sql` file:**
```bash
snow sql -c hf -f path/to/query.sql
```

**Override defaults per call:**
```bash
snow sql -c hf --role <ROLE> --warehouse <WH> --database <DB> -q "..."
```

## Output formats

- Default (`table`) renders nicely for narrow results but mangles wide rows — switch formats for anything beyond a few columns.
- `--format csv` — best for piping into a file or showing tabular results to the user.
- `--format json` — best for programmatic parsing.

```bash
snow sql -c hf --format csv -q "..." > output.csv
```

## Workflow

1. **Sanity-check first.** For anything non-trivial, run with `LIMIT 10` (or wrap as `SELECT * FROM (...) LIMIT 10`) before the full run. Snowflake credits are real.
2. **Be explicit about the role/warehouse** if the query touches a database outside `US_OPS_ANALYTICS`. Use the `snowflake-discover` skill to find the right one.
3. **Long-running queries** — pass `--timeout` to bash (default 2 min is often too short). Example: `timeout: 300000` for 5 min.
4. **Show the user what ran.** When you execute, include the query (or filename) in your reply so they can repro.
5. **Don't leak large result sets into context.** Pipe to a file and summarize (row count, sample rows) instead of dumping everything.

## Auth gotchas

- First query of a session pops a browser window for Azure SSO; subsequent calls reuse the cached token.
- If you see `390195 (08001): Authentication token has expired`, just rerun — the next call will reauthenticate.
- Don't edit `~/Library/Application Support/snowflake/config.toml` to add passwords or keys — this user is on SSO.

## Common HF references

- Forecasts: `US_OPS_ANALYTICS.FORECAST.MV_HF_FORECAST_RECIPES`
- Production kit guides: `US_OPS_ANALYTICS.GOOGLE_DRIVE.PRODUCTION_KIT_GUIDES`
- Culinary SKUs: `US_OPS_ANALYTICS.SPS.CULINARY_SKU_GENERAL`
- Add-on calendar: `US_OPS_ANALYTICS.GOOGLE_DRIVE.ADD_ON_MENU_CALENDAR`
