-- Catalogue-backed completion for the CLI dadbod adapters
-- (databricks:photon, snowflake:hf).
--
-- Why this exists: vim-dadbod-completion filters candidates with an anchored
-- regex (^<base>), which never matches fully-qualified catalogue entries
-- (glue.<db>.<table>) when you type a fragment from the middle of the name.
-- This source returns the curated list as-is and lets nvim-cmp's fuzzy
-- matcher do the filtering, with a per-database badge in the detail column.
--
-- Lists come from ~/.local/share/nvim/db-catalogue/*.tables (+ badges.tsv
-- for the per-database menu badge), written by hf-db-catalogue-refresh
-- (:SqlCatalogueRefresh). Kept HF-internal detail out of this file on
-- purpose: this config repo is public.
local cmp = require("cmp")

local catalogue_dir = vim.fn.stdpath("data") .. "/db-catalogue"

local source = {}
source.__index = source

function source.new()
  return setmetatable({}, source)
end

local function catalogue_file()
  local db = vim.b.db
  if type(db) ~= "string" then
    return nil
  end
  if db:match("^databricks:") then
    return catalogue_dir .. "/databricks.tables"
  end
  if db:match("^snowflake:") then
    return catalogue_dir .. "/snowflake.tables"
  end
  return nil
end

function source:is_available()
  return catalogue_file() ~= nil
end

function source:get_debug_name()
  return "db-catalogue"
end

-- Cache per file + mtimes so a :SqlCatalogueRefresh is picked up
-- automatically. Badges (db -> short label) come from badges.tsv.
local cache = {}

local function load_badges()
  local badges = {}
  local fd = io.open(catalogue_dir .. "/badges.tsv", "r")
  if fd then
    for line in fd:lines() do
      local db, badge = line:match("^([^\t]+)\t([^\t]+)$")
      if db then badges[db] = badge end
    end
    fd:close()
  end
  return badges
end

local function items_for(file)
  local mtime = vim.fn.getftime(file)
  local badges_mtime = vim.fn.getftime(catalogue_dir .. "/badges.tsv")
  local hit = cache[file]
  if hit and hit.mtime == mtime and hit.badges_mtime == badges_mtime then
    return hit.items
  end
  local badges = load_badges()
  local items = {}
  local fd = io.open(file, "r")
  if not fd then
    return items
  end
  for line in fd:lines() do
    -- glue.<db>.<table> or DB.SCHEMA.TABLE — badge on the database part.
    local dbname = line:match("^glue%.([^.]+)%.") or line:match("^([^.]+)%.")
    table.insert(items, {
      label = line,
      kind = cmp.lsp.CompletionItemKind.Struct,
      detail = dbname and (badges[dbname] or dbname) or "?",
    })
  end
  fd:close()
  cache[file] = { mtime = mtime, badges_mtime = badges_mtime, items = items }
  return items
end

function source:complete(_, callback)
  local file = catalogue_file()
  if not file or vim.fn.filereadable(file) == 0 then
    callback({ items = {}, isIncomplete = false })
    return
  end
  callback({ items = items_for(file), isIncomplete = false })
end

return source
