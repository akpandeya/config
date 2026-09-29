-- Catalogue-backed completion for read_sql-style strings in python buffers.
--
-- Reads flat files from ~/.local/share/nvim/db-catalogue/ (written by
-- hf-db-catalogue-refresh / :SqlCatalogueRefresh):
--   snowflake.tables          DB.SCHEMA.TABLE           (backend sf)
--   databricks.tables         glue.<db>.<table>         (backend dbx)
--   postgres.<svc>.tables     schema.table              (backend pg:<svc>)
--   postgres.<svc>.columns    schema.table<TAB>column   (backend pg:<svc>)
--
-- pg uses the same static catalogue as the CLI backends on purpose:
-- vim-dadbod-completion (used for pg in .sql buffers) hard-gates itself to
-- sql filetypes and can't be reused in python buffers without fragile
-- plugin-internal hacks. pg catalogues are cheap to enumerate, so static
-- files cost nothing here.
--
-- The backend comes from db-python.backend_for (not b:db), and completion
-- only fires inside read_sql("...") strings (db-python.in_sql_string).
local cmp = require("cmp")
local resolver = require("db-python")

local catalogue_dir = vim.fn.stdpath("data") .. "/db-catalogue"

local source = {}
source.__index = source

function source.new()
  return setmetatable({}, source)
end

function source:is_available()
  return vim.bo.filetype == "python"
end

function source:get_debug_name()
  return "db-python-catalogue"
end

local function files_for(kind, detail)
  if kind == "sf" then
    return { catalogue_dir .. "/snowflake.tables" }
  end
  if kind == "dbx" then
    return { catalogue_dir .. "/databricks.tables" }
  end
  if kind == "pg" and detail then
    return {
      catalogue_dir .. "/postgres." .. detail .. ".tables",
      catalogue_dir .. "/postgres." .. detail .. ".columns",
    }
  end
  return {}
end

-- Cache per file + mtime so a :SqlCatalogueRefresh is picked up
-- automatically. Badges (db -> short label) come from badges.tsv.
local cache = {}
local badges_cache = { mtime = -1, badges = {} }

local function load_badges()
  local mtime = vim.fn.getftime(catalogue_dir .. "/badges.tsv")
  if badges_cache.mtime == mtime then
    return badges_cache.badges
  end
  local badges = {}
  local fd = io.open(catalogue_dir .. "/badges.tsv", "r")
  if fd then
    for line in fd:lines() do
      local db, badge = line:match("^([^\t]+)\t([^\t]+)$")
      if db then badges[db] = badge end
    end
    fd:close()
  end
  badges_cache = { mtime = mtime, badges = badges }
  return badges
end

local function items_for(file, fallback_detail)
  local mtime = vim.fn.getftime(file)
  local hit = cache[file]
  if hit and hit.mtime == mtime then
    return hit.items
  end
  local badges = load_badges()
  local items = {}
  local seen_columns = {}
  local fd = io.open(file, "r")
  if not fd then
    return items
  end
  for line in fd:lines() do
    local table_name, column = line:match("^([^\t]+)\t([^\t]+)$")
    if column then
      -- Columns repeat across tables; keep the first (its table as detail).
      if not seen_columns[column] then
        seen_columns[column] = true
        table.insert(items, {
          label = column,
          kind = cmp.lsp.CompletionItemKind.Field,
          detail = table_name,
        })
      end
    else
      -- glue.<db>.<table> or DB.SCHEMA.TABLE — badge on the database part.
      local dbname = line:match("^glue%.([^.]+)%.") or line:match("^([^.]+)%.")
      table.insert(items, {
        label = line,
        kind = cmp.lsp.CompletionItemKind.Struct,
        detail = (dbname and (badges[dbname] or dbname)) or fallback_detail or "?",
      })
    end
  end
  fd:close()
  cache[file] = { mtime = mtime, items = items }
  return items
end

local function backend_items()
  local items = {}
  for _, b in ipairs(resolver.backend_candidates()) do
    local detail = b == "sf" and "snowflake (snow CLI)"
      or b == "dbx" and "databricks (photon)"
      or "postgres service"
    table.insert(items, {
      label = b,
      kind = cmp.lsp.CompletionItemKind.Value,
      detail = detail,
    })
  end
  return items
end

function source:complete(params, callback)
  local empty = { items = {}, isIncomplete = false }
  local line = params.context.cursor_before_line

  -- Case 1: "# backend: ..." comment → backend names.
  if line:match("^%s*#%s*backend:") then
    callback({ items = backend_items(), isIncomplete = false })
    return
  end

  -- Case 2: inside a read_sql-style string.
  if not resolver.in_sql_string() then
    callback(empty)
    return
  end

  -- Case 2a: backend-arg string — text since the opening quote is a single
  -- backend-shaped token ("pg:", "dbx", ...). Mid-SQL fragments can't reach
  -- this: they contain spaces, so they fail the quote-adjacent token match.
  local frag = line:match('["\']([%w:_-]*)$')
  if frag and resolver.is_backend_fragment(frag) then
    callback({ items = backend_items(), isIncomplete = false })
    return
  end

  -- Case 2b: SQL string → catalogue tables/columns for the buffer backend.
  local kind, detail = resolver.backend_kind(resolver.backend_for(0))
  local items = {}
  for _, file in ipairs(files_for(kind, detail)) do
    if vim.fn.filereadable(file) == 1 then
      vim.list_extend(items, items_for(file, detail))
    end
  end
  callback({ items = items, isIncomplete = false })
end

return source
