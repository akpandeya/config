---
name: snowflake-discover
description: Discover available Snowflake roles, warehouses, databases, schemas, and tables for the current user using the `snow` CLI. Use when the user asks what they can access in Snowflake, which warehouse/role to use, or where a table lives.
allowed-tools: Bash, Read
---

You're helping the user discover what they can access in HelloFresh Snowflake via the `snow` CLI (Snowflake CLI). The connection `hf` is already configured in `~/Library/Application Support/snowflake/config.toml` with externalbrowser SSO.

## Ground rules

- Always use `snow sql -c hf` (the `hf` connection has SSO + sensible defaults wired up).
- Prefer `--format json` or `--format csv` over the default table format — wide rows get mangled in the table renderer.
- For broad listings (warehouses, databases) parse JSON with a small `python3 -c` snippet rather than dumping raw JSON to the user.
- Switch role with `USE ROLE <ROLE>;` in the same `-q` statement when the default role can't see something — Snowflake permits multi-statement `-q`.

## Common discovery queries

**Who am I / what roles do I have:**
```bash
snow sql -c hf -q "SELECT CURRENT_USER() AS user, CURRENT_ROLE() AS role, CURRENT_AVAILABLE_ROLES() AS available_roles;"
```

**Warehouses:**
```bash
snow sql -c hf --format json -q "SHOW WAREHOUSES;" | python3 -c "import sys,json; [print(f\"  {r['name']}  size={r.get('size')}  state={r.get('state')}\") for r in json.load(sys.stdin)[-1]]"
```

**Databases (may need a broader role):**
```bash
snow sql -c hf --format json -q "USE ROLE <ROLE>; SHOW DATABASES;" | python3 -c "import sys,json; [print(f\"  {r['name']}\") for r in json.load(sys.stdin)[-1]]"
```

**Schemas in a database:**
```bash
snow sql -c hf -q "SHOW SCHEMAS IN DATABASE <DB>;"
```

**Tables in a schema:**
```bash
snow sql -c hf -q "SHOW TABLES IN SCHEMA <DB>.<SCHEMA>;"
```

**Search for a table by name across the account:**
```bash
snow sql -c hf -q "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ROW_COUNT FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES WHERE TABLE_NAME ILIKE '%<pattern>%' AND DELETED IS NULL LIMIT 50;"
```

**Columns on a table:**
```bash
snow sql -c hf -q "DESC TABLE <DB>.<SCHEMA>.<TABLE>;"
```

**What grants does a role have:**
```bash
snow sql -c hf -q "SHOW GRANTS TO ROLE <ROLE>;"
```

## Workflow tips

- If a `SHOW` returns "does not exist or not authorized", try a broader role first (e.g. `US_OPS_ANALYTICS_ENGINEER_NONSENSITIVE`) before assuming the object is missing.
- `SNOWFLAKE.ACCOUNT_USAGE.*` views are great for cross-database search but lag by up to 2 hours and require role access — fall back to `INFORMATION_SCHEMA` per-database if blocked.
- Don't dump 100s of rows — summarize. The user usually wants a name to use, not a complete inventory.
