-- Shared helpers for DB-in-Python tooling (pyscratch.lua, db-python-cmp.lua).
--
-- Backend resolution order for a python buffer:
--   1. b:db_backend          (set by :DBBackend)
--   2. "# backend: <name>"   comment in the first 10 lines (persistent)
--   3. "sf"                  default
--
-- Backend names: sf | snowflake[:conn] | dbx | databricks | photon |
-- pg:<service> | postgres:<service> | bare pg service name.
--
-- The treesitter gate (in_sql_string) decides whether completion should
-- offer SQL items: cursor must be inside a string that is an argument of a
-- call named read_sql/execute/query/sql (attribute calls like
-- pd.read_sql(...) count — only the last identifier is matched).

local M = {}

local SQL_CALLS = { read_sql = true, execute = true, query = true, sql = true }
local STRING_TYPES = { string = true, concatenated_string = true }

-- ---------------------------------------------------------------- pg services

local services_cache = { mtime = -1, names = {} }

--- Stanza names from the libpq service file (names only, never values).
function M.pg_services()
  local services_file = vim.env.PGSERVICEFILE or (vim.env.HOME .. "/.pg_service.conf")
  local mtime = vim.fn.getftime(services_file)
  if services_cache.mtime == mtime then
    return services_cache.names
  end
  local names = {}
  local f = io.open(services_file, "r")
  if f then
    for line in f:lines() do
      local name = line:match("^%[([^%]]+)%]")
      if name then table.insert(names, name) end
    end
    f:close()
  end
  services_cache = { mtime = mtime, names = names }
  return names
end

-- ---------------------------------------------------------------- backend

--- Backend string for a buffer (see header for resolution order).
function M.backend_for(buf)
  buf = buf or vim.api.nvim_get_current_buf()
  local ok, explicit = pcall(function() return vim.b[buf].db_backend end)
  if ok and type(explicit) == "string" and explicit ~= "" then
    return explicit
  end
  for _, line in ipairs(vim.api.nvim_buf_get_lines(buf, 0, 10, false)) do
    local b = line:match("^%s*#%s*backend:%s*(%S+)")
    if b then return b end
  end
  return "sf"
end

--- → "pg", service|nil  |  "sf"  |  "dbx"
function M.backend_kind(backend)
  local low = backend:lower()
  local colon = low:find(":", 1, true)
  if colon and (low:sub(1, colon - 1) == "pg" or low:sub(1, colon - 1) == "postgres") then
    return "pg", backend:sub(colon + 1)
  end
  if low == "sf" or low:match("^snowflake") then return "sf" end
  if low == "dbx" or low == "databricks" or low == "photon" then return "dbx" end
  if vim.tbl_contains(M.pg_services(), backend) then return "pg", backend end
  return "sf"
end

-- ---------------------------------------------------------------- backend completion

local BACKEND_PREFIXES = { "sf", "dbx", "pg", "postgres", "snowflake", "databricks", "photon" }

--- Completion candidates for backend strings: sf, dbx, pg:<service>...
function M.backend_candidates()
  local items = { "sf", "dbx" }
  for _, s in ipairs(M.pg_services()) do
    table.insert(items, "pg:" .. s)
  end
  return items
end

--- True when `text` (string content typed so far) looks like a backend
--- fragment rather than SQL: a single token (no spaces) starting with a
--- backend prefix — e.g. "pg", "pg:assembly-", "dbx".
function M.is_backend_fragment(text)
  if not text:match("^[%w:_-]*$") then return false end
  local low = text:lower()
  for _, p in ipairs(BACKEND_PREFIXES) do
    if low:sub(1, #p) == p then return true end
  end
  return false
end

-- ---------------------------------------------------------------- treesitter gate

--- True when the cursor is inside a string argument of a read_sql-style call.
function M.in_sql_string()
  -- Force a synchronous parse: callers (cmp entry_filter/complete) run per
  -- keystroke and the tree may not be parsed yet (async in 0.12, headless).
  -- Incremental reparse of a scratch-sized file is cheap.
  local ok, parser = pcall(vim.treesitter.get_parser, 0)
  if not ok or not parser then return false end
  parser:parse(true)
  local node = vim.treesitter.get_node()
  if not node then return false end

  while node and not STRING_TYPES[node:type()] do
    node = node:parent()
  end
  if not node then return false end

  local arglist = node:parent()
  while arglist and arglist:type() ~= "argument_list" do
    arglist = arglist:parent()
  end
  if not arglist then return false end

  local call = arglist:parent()
  if not call or call:type() ~= "call" then return false end

  local fn = call:field("function")[1]
  if not fn then return false end
  local name = vim.treesitter.get_node_text(fn, 0):match("([%w_]+)$")
  return SQL_CALLS[name] == true
end

return M
