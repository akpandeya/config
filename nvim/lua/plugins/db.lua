-- Database tooling: vim-dadbod + UI + completion.
--
-- Postgres connections come from the same pg_service.conf that drives
-- `fpsql` (shell/pg.sh) — parsed into g:dbs as `postgres://?service=<name>`
-- URLs so psql/libpq keeps resolving hosts/auth exactly like the CLI does.
-- Snowflake + Databricks are extra_connections: CLI-shelling dadbod adapters
-- (autoload/db/adapter/*.vim → `snow sql` / `hf-photon`). Their DBUI table
-- list + completion come from a curated catalogue file
-- (scripts/refresh-db-catalogue.sh) — the glue catalog is far too big to
-- enumerate live at expand time.
--
--   :DBUI                 schema browser (<leader>D)
--   :SqlScratch [service] per-service scratch buffer (b:db pre-bound)
--   :SqlHistory [service] log of every query executed against a service
--   :SqlCatalogueRefresh  rebuild the snowflake/databricks table lists
--   visual <leader>E      execute selection against the buffer's connection

local services_file = vim.env.PGSERVICEFILE or (vim.env.HOME .. "/.pg_service.conf")

-- Parse [stanza] names out of the service file.
local function services()
  local names = {}
  local f = io.open(services_file, "r")
  if not f then return names end
  for line in f:lines() do
    local name = line:match("^%[([^%]]+)%]")
    if name then table.insert(names, name) end
  end
  f:close()
  return names
end

local function db_url(service)
  return "postgres://?service=" .. service
end

-- Non-Postgres backends, reached through CLI-shelling dadbod adapters
-- (nvim/autoload/db/adapter/{snowflake,databricks}.vim). DBUI shows a flat
-- Tables list behind them (curated catalogue, see :SqlCatalogueRefresh).
local extra_connections = {
  ["snowflake:hf"] = "snowflake:hf",
  ["databricks:photon"] = "databricks:photon",
}

local function conn_url(name)
  return extra_connections[name] or db_url(name)
end

-- pg services + CLI-backed connections, for pickers and completion.
local function connections()
  local names = services()
  for name in pairs(extra_connections) do
    table.insert(names, name)
  end
  table.sort(names)
  return names
end

-- Query history: every executed query is appended to a per-service log in
-- stdpath("data")/sql-history, so past queries survive scratch overwrites.
local history_dir = vim.fn.stdpath("data") .. "/sql-history"

local function history_path(url)
  -- pg service URLs and the snowflake:hf / databricks:photon labels are all
  -- credential-free; raw URLs may carry credentials in userinfo — strip
  -- those before using the URL as a filename.
  local service = url and url:match("service=([^&]+)")
  if not service and url and url:match("^[%w_]+:[%w_-]+$") then
    service = url:gsub(":", "-")
  end
  if not service then
    service = (url or "unknown"):gsub("://[^/@]*@", "://@"):gsub("[^%w%-_]", "_")
  end
  return history_dir .. "/" .. service .. ".sql", service
end

-- Fires on User <outfile>.dbout/DBExecutePost. The current buffer at that
-- point is the SQL buffer, so resolve the dbout buffer from the event match
-- and read dadbod's query dict ({db_url, input=query file, ...}) off it.
local function log_query(ev)
  local output = ev.match:match("^(.*)/DBExecutePost$")
  local buf = output and vim.fn.bufnr(output) or -1
  if buf < 0 then return end
  local d = vim.fn.getbufvar(buf, "db")
  if type(d) ~= "table" then return end
  local f = io.open(d.input or "", "r")
  if not f then return end
  local query = vim.trim(f:read("*a") or "")
  f:close()
  if query == "" then return end

  vim.fn.mkdir(history_dir, "p")
  local path = history_path(d.db_url)
  local h = io.open(path, "a")
  if not h then return end
  h:write("-- " .. os.date("%Y-%m-%d %H:%M:%S") .. "\n" .. query .. "\n\n")
  h:close()
end

local function open_history(service)
  local path = history_path(conn_url(service))
  if vim.fn.filereadable(path) == 0 then
    vim.notify("No query history for " .. service, vim.log.levels.WARN)
    return
  end
  vim.cmd.edit(vim.fn.fnameescape(path))
  vim.bo.filetype = "sql"
end

-- Populate g:dbs (DBUI connection list) from the service file.
-- NOTE: build the Lua table first and assign once — `vim.g.dbs = {}` becomes
-- a Vim *list* (empty-table ambiguity) and silently swallows string keys.
local function setup_connections()
  local dbs = {}
  for _, name in ipairs(services()) do
    dbs[name] = db_url(name)
  end
  for name, url in pairs(extra_connections) do
    dbs[name] = url
  end
  if next(dbs) ~= nil then vim.g.dbs = dbs end
end

local function open_scratch(service)
  -- Ensure dadbod is loaded so b:db has an adapter behind it (SqlScratch is
  -- created in init() at startup, outside lazy.nvim's cmd stubs).
  require("lazy").load({ plugins = { "vim-dadbod" } })
  local dir = vim.fn.stdpath("data") .. "/sql-scratch"
  vim.fn.mkdir(dir, "p")
  local path = dir .. "/" .. service:gsub(":", "-") .. ".sql"
  vim.cmd.edit(vim.fn.fnameescape(path))
  vim.bo.filetype = "sql"
  vim.b.db = conn_url(service)
end

local function pick_service(cb)
  local ok, pickers = pcall(require, "telescope.pickers")
  if not ok then
    vim.ui.select(connections(), { prompt = "Service:" }, cb)
    return
  end
  local finders = require("telescope.finders")
  local conf = require("telescope.config").values
  local actions = require("telescope.actions")
  local action_state = require("telescope.actions.state")

  pickers.new({}, {
    prompt_title = "Service",
    finder = finders.new_table({ results = connections() }),
    sorter = conf.generic_sorter({}),
    previewer = false,
    attach_mappings = function(prompt_bufnr, _)
      actions.select_default:replace(function()
        local sel = action_state.get_selected_entry().value
        actions.close(prompt_bufnr)
        cb(sel)
      end)
      return true
    end,
  }):find()
end

local function sql_scratch(args)
  local service = args.args
  if service == "" then
    pick_service(function(sel)
      if sel then open_scratch(sel) end
    end)
  else
    open_scratch(service)
  end
end

-- Result-buffer (dbout) rendering + niceties.
--
-- Default view is compact: columns are sized to fit the window, long
-- values truncate with `…`, every column stays visible (nowrap). The
-- full parsed table lives in b:dbout_rows — gj pretty-prints the cell
-- under cursor from the stash, gr transposes the row vertically,
-- <Leader>R toggles compact ↔ full-width. Output we can't parse (errors,
-- \x records, snowflake TABLE grids) keeps dadbod's raw rendering with
-- the old yank-based gj/gr.
local function open_value_split(text, filetype)
  vim.cmd("vsplit")
  vim.cmd("enew")
  local buf = vim.api.nvim_get_current_buf()
  vim.bo[buf].buftype = "nofile"
  vim.bo[buf].bufhidden = "wipe"
  vim.bo[buf].filetype = filetype
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, vim.split(text, "\n"))
  return buf
end

local function pretty_json(text)
  if vim.fn.executable("jq") == 1 then
    local out = vim.fn.system({ "jq", "." }, text)
    if vim.v.shell_error == 0 then return out:gsub("\n$", "") end
  end
  return text
end

-- Describe a table in the buffer's connection: `describe table` for the
-- CLI-backed adapters, information_schema for postgres (psql \d meta-
-- commands don't work through dadbod). Table name from the arg or the
-- WORD under cursor (<cWORD> so dotted `glue.db.table` names stay whole).
local function describe_table(name)
  local url = vim.b.db
  if not url then
    vim.notify("No connection bound — open the buffer with :SqlScratch", vim.log.levels.WARN)
    return
  end
  name = vim.trim(name or "")
  if name == "" then name = vim.fn.expand("<cWORD>") end
  if name == "" or name:find("[%s;]") then
    vim.notify("No table name under cursor (or pass one: :SqlDescribe db.schema.tbl)", vim.log.levels.WARN)
    return
  end
  require("lazy").load({ plugins = { "vim-dadbod" } })
  local query
  if url:match("^postgres") then
    local schema, tbl = name:match("^([%w_]+)%.(%w+)$")
    if schema then
      query = string.format(
        "select column_name, data_type, is_nullable from information_schema.columns where table_schema = '%s' and table_name = '%s' order by ordinal_position",
        schema, tbl)
    else
      query = string.format(
        "select table_schema, column_name, data_type, is_nullable from information_schema.columns where table_name = '%s' order by table_schema, ordinal_position",
        name)
    end
  else
    query = "describe table " .. name
  end
  vim.cmd("DB " .. url .. " " .. query)
end

-- List every table available on the buffer's connection. Snowflake/
-- databricks: the curated catalogue file (offline, no live query — same
-- source as completion). Postgres: a live information_schema query.
-- <leader>dT in sql buffers.
local function list_tables()
  local url = vim.b.db
  if not url then
    vim.notify("No connection bound — open the buffer with :SqlScratch", vim.log.levels.WARN)
    return
  end
  require("lazy").load({ plugins = { "vim-dadbod" } })
  if url:match("^postgres") then
    vim.cmd("DB " .. url
      .. " select table_schema, table_name from information_schema.tables"
      .. " where table_schema not in ('pg_catalog', 'information_schema')"
      .. " order by 1, 2")
    return
  end
  local kind = url:match("^([%w_]+):")
  local file = vim.fn.stdpath("data") .. "/db-catalogue/" .. kind .. ".tables"
  if vim.fn.filereadable(file) == 0 then
    vim.notify("No catalogue yet — run :SqlCatalogueRefresh", vim.log.levels.WARN)
    return
  end
  vim.cmd("vsplit " .. vim.fn.fnameescape(file))
  vim.bo.readonly = true
  vim.bo.buflisted = false
end

local function content_sig(lines)
  return #lines .. "|" .. (lines[1] or "") .. "|" .. (lines[#lines] or "")
end

-- psql aligned format: the '+' positions in the separator line are the
-- exact column boundaries, so slicing every line at those positions is
-- immune to '|' characters that appear inside values.
local function parse_aligned(lines)
  local sep = lines[2]
  if not (sep and sep:match("^[%-+ ]+$") and sep:find("%-")) then return nil end
  local bounds = {}
  local from = 1
  while true do
    local b = sep:find("+", from, true)
    if not b then break end
    bounds[#bounds + 1] = b
    from = b + 1
  end
  local function slice(line, i)
    if #bounds == 0 then return vim.trim(line) end
    local a = i == 1 and 1 or bounds[i - 1] + 1
    local b = i <= #bounds and bounds[i] - 1 or #line
    return vim.trim(line:sub(a, b))
  end
  local ncols = #bounds == 0 and 1 or (#bounds + 1)
  local rows = {}
  local header = {}
  for i = 1, ncols do header[i] = slice(lines[1], i) end
  rows[1] = header
  for n = 3, #lines do
    local line = lines[n]
    if line:match("^%s*%(%d+ rows?%)") then break end
    if vim.trim(line) ~= "" then
      local row = {}
      for i = 1, ncols do row[i] = slice(line, i) end
      rows[#rows + 1] = row
    end
  end
  return rows
end

-- databricks hf-photon TSV (one physical line per row, tab-separated).
local function parse_tsv(lines)
  if not (lines[1] and lines[1]:find("\t")) then return nil end
  local function split(line)
    local cells = vim.fn.split(line, "\t", 1)
    for i = #cells, 1, -1 do cells[i] = cells[i]:gsub("\r$", "") end
    return cells
  end
  local rows = {}
  rows[1] = split(lines[1])
  local ncols = #rows[1]
  for n = 2, #lines do
    local line = lines[n]
    if line:match("^%s*%(%d+ rows?%)") then break end
    if vim.trim(line) ~= "" then
      local row = split(line)
      for i = ncols + 1, #row do row[i] = nil end
      for i = #row + 1, ncols do row[i] = "" end
      rows[#rows + 1] = row
    end
  end
  return rows
end

local function parse_dbout(lines)
  if #lines == 0 then return nil end
  return parse_aligned(lines) or parse_tsv(lines)
end

-- Flatten control chars: cells render on one physical line each; real
-- newlines inside values are only visible via gj/gr.
local function dbout_display(s)
  return (s or ""):gsub("[\r\n\t]+", " ")
end

local function trunc_ellipsis(s, width)
  if width < 1 then return "" end
  if vim.fn.strdisplaywidth(s) <= width then return s end
  local cut = vim.fn.strcharpart(s, 0, width - 1)
  while vim.fn.strdisplaywidth(cut) > width - 1 do
    cut = vim.fn.strcharpart(cut, 0, vim.fn.strchars(cut) - 1)
  end
  return cut .. "…"
end

local function pad_cell(s, w)
  local pad = w - vim.fn.strdisplaywidth(s)
  return pad > 0 and (s .. string.rep(" ", pad)) or s
end

local function natural_widths(rows)
  local widths = {}
  for c = 1, #rows[1] do
    local max = 1
    for r = 1, #rows do
      max = math.max(max, vim.fn.strdisplaywidth(dbout_display(rows[r][c])))
    end
    widths[c] = max
  end
  return widths
end

-- Fit all columns into `usable` display columns: narrow columns keep
-- their full width, wide ones share the rest proportionally (min 1 char).
local function compute_widths(rows, usable)
  local ncols = #rows[1]
  usable = math.max(usable, ncols)
  local natural = natural_widths(rows)
  local total = 0
  for _, w in ipairs(natural) do total = total + w end
  if total <= usable then return natural end
  local base = math.floor(usable / ncols)
  local widths, used, big, big_total = {}, 0, {}, 0
  for c = 1, ncols do
    if natural[c] <= base then
      widths[c] = natural[c]
      used = used + natural[c]
    else
      big[#big + 1] = c
      big_total = big_total + natural[c]
    end
  end
  local left = math.max(usable - used, #big)
  for _, c in ipairs(big) do
    widths[c] = math.max(math.floor(left * natural[c] / big_total), 1)
  end
  return widths
end

-- Render rows at the given widths; returns the buffer lines and the
-- display-column position where each cell starts (for cursor → cell).
local function render_table(rows, widths)
  local ncols = #rows[1]
  local starts, start = {}, 2
  for c = 1, ncols do
    starts[c] = start
    start = start + widths[c] + 3
  end
  local function fmt_row(row)
    local parts = {}
    for c = 1, ncols do
      parts[c] = pad_cell(trunc_ellipsis(dbout_display(row[c]), widths[c]), widths[c])
    end
    return " " .. table.concat(parts, " | ")
  end
  local lines = { fmt_row(rows[1]) }
  local dashes = {}
  for c = 1, ncols do dashes[c] = string.rep("-", widths[c]) end
  lines[2] = " " .. table.concat(dashes, "-+-")
  for r = 2, #rows do lines[#lines + 1] = fmt_row(rows[r]) end
  return lines, starts
end

local function dbout_window_width()
  local win = vim.fn.bufwinnr("%")
  if win > 0 then return vim.fn.winwidth(win) - 2 end
  return math.floor(vim.o.columns / 2) - 2
end

-- Redraw the current dbout buffer at the given layout.
local function set_layout(compact)
  local rows = vim.b.dbout_rows
  if type(rows) ~= "table" or #rows == 0 or #(rows[1] or {}) == 0 then return end
  vim.b.dbout_compact = compact
  vim.opt_local.wrap = not compact
  local widths = compact and compute_widths(rows, dbout_window_width())
    or natural_widths(rows)
  local lines, starts = render_table(rows, widths)
  vim.api.nvim_buf_set_lines(0, 0, -1, false, lines)
  vim.b.dbout_starts = starts
  vim.b.dbout_render_sig = content_sig(lines)
end

-- Cell under cursor from the stash (rendered lines are truncated; buffer
-- text is not the source of truth). Returns value, row_index, col_index.
local function cell_at_cursor()
  local rows = vim.b.dbout_rows
  local starts = vim.b.dbout_starts
  if type(rows) ~= "table" or type(starts) ~= "table" then return nil end
  local r = vim.fn.line(".") - 1 -- buffer line 3 = rows[2]
  if r < 2 or r > #rows then return nil end
  local col, c = vim.fn.virtcol("."), 1
  for i = 1, #starts do
    if starts[i] <= col then c = i else break end
  end
  local row = rows[r]
  return (row and row[c]) or "", r, c
end

local function apply_dbout_maps(compact)
  if not compact then
    -- Unparsed output: fall back to the yank-based helpers. <Leader>R is
    -- left to dadbod-ui.
    vim.keymap.set("n", "gj", function()
      vim.cmd('execute "normal vic"')
      vim.cmd("normal! y")
      local cell = vim.trim(vim.fn.getreg('"'))
      if cell == "" then return end
      open_value_split(pretty_json(cell), "json")
    end, { buffer = true, desc = "Pretty-print cell JSON in split" })
    vim.keymap.set("n", "gr", function()
      local header = vim.fn.getline(1)
      local row = vim.fn.getline(".")
      if not header:find("\t") or not row:find("\t") then
        vim.notify("gr: only works on tab-separated output (databricks)", vim.log.levels.WARN)
        return
      end
      local cols = vim.fn.split(header, "\t")
      local vals = vim.fn.split(row, "\t")
      local width = 1
      for _, c in ipairs(cols) do width = math.max(width, #c) end
      local lines = {}
      for i, c in ipairs(cols) do
        table.insert(lines, string.format("%-" .. width .. "s  %s", c, vals[i] or ""))
      end
      local buf = open_value_split(table.concat(lines, "\n"), "dbout-transpose")
      vim.keymap.set("n", "gj", function()
        local val = vim.fn.getline("."):match("^%S+%s%s+(.*)$") or ""
        if val == "" then return end
        open_value_split(pretty_json(val), "json")
      end, { buffer = buf, desc = "Pretty-print value JSON in split" })
    end, { buffer = true, desc = "Transpose row into vertical key:value view" })
    return
  end

  vim.keymap.set("n", "gj", function()
    local cell = cell_at_cursor()
    if not cell or vim.trim(cell) == "" then
      vim.notify("No cell value under cursor", vim.log.levels.WARN)
      return
    end
    open_value_split(pretty_json(cell), "json")
  end, { buffer = true, desc = "Pretty-print cell JSON in split" })

  vim.keymap.set("n", "gr", function()
    local rows = vim.b.dbout_rows
    local _, r = cell_at_cursor()
    if not r then
      vim.notify("gr: cursor is on the header, not a row", vim.log.levels.WARN)
      return
    end
    local header, row = rows[1], rows[r]
    local width = 1
    for _, h in ipairs(header) do width = math.max(width, vim.fn.strdisplaywidth(h)) end
    local lines = {}
    for i, h in ipairs(header) do
      table.insert(lines, string.format("%-" .. width .. "s  %s", h, row[i] or ""))
    end
    local buf = open_value_split(table.concat(lines, "\n"), "dbout-transpose")
    -- gj on a transposed line: pretty-print that column's value as JSON.
    vim.keymap.set("n", "gj", function()
      local val = vim.fn.getline("."):match("^%S+%s%s+(.*)$") or ""
      if val == "" then return end
      open_value_split(pretty_json(val), "json")
    end, { buffer = buf, desc = "Pretty-print value JSON in split" })
  end, { buffer = true, desc = "Transpose row into vertical key:value view" })

  -- Ours overrides dadbod-ui's <Leader>R (registered later wins): toggle
  -- compact ↔ full-width, both rendered from the same stash.
  vim.keymap.set("n", "<Leader>R", function()
    set_layout(vim.b.dbout_compact == false)
  end, { buffer = true, desc = "Toggle compact/full-width output" })
end

local function setup_dbout()
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  local sig = content_sig(lines)
  -- Content unchanged since the last pass: just refresh mappings.
  if vim.b.dbout_raw_sig == sig then
    apply_dbout_maps(true)
    return
  end
  if vim.b.dbout_render_sig == sig then
    apply_dbout_maps(vim.b.dbout_compact ~= false)
    return
  end
  local rows = parse_dbout(lines)
  if not rows or #rows == 0 or #(rows[1] or {}) == 0 then
    for _, v in ipairs({ "dbout_rows", "dbout_starts", "dbout_raw_sig",
                         "dbout_render_sig", "dbout_compact" }) do
      pcall(vim.api.nvim_buf_del_var, 0, v)
    end
    apply_dbout_maps(false)
    return
  end
  vim.b.dbout_raw_sig = sig
  vim.b.dbout_rows = rows
  set_layout(true)
  apply_dbout_maps(true)
end

return {
  {
    "tpope/vim-dadbod",
    cmd = { "DB", "DBUI", "DBUIToggle", "DBUIFindBuffer" },
    dependencies = {
      { "kristijanhusak/vim-dadbod-ui" },
      { "kristijanhusak/vim-dadbod-completion", ft = { "sql" } },
    },
    init = function()
      vim.g.db_ui_use_nerd_fonts = 1
      vim.g.db_ui_auto_execute_table_helpers = 1
      -- Catalogue tables are fully qualified (glue.db.table / DB.SCHEMA.TABLE);
      -- the default List helper wraps {table} in double quotes, which breaks
      -- dotted names on both backends — use unquoted variants.
      vim.g.db_ui_table_helpers = {
        databricks = {
          List = "select * from {table} limit 200",
          Columns = "describe table {table}",
        },
        snowflake = {
          List = "select * from {table} limit 200",
          Columns = "describe table {table}",
        },
      }
      setup_connections()

      vim.api.nvim_create_autocmd("FileType", {
        group = vim.api.nvim_create_augroup("dbout-json", { clear = true }),
        pattern = "dbout",
        callback = setup_dbout,
      })

      -- Insurance: some dadbod flows leave the output buffer without the
      -- dbout filetype (no wrap, no mappings) — re-apply by filename.
      -- setup_dbout is idempotent (buffer-local maps just get overwritten).
      vim.api.nvim_create_autocmd("BufEnter", {
        group = vim.api.nvim_create_augroup("dbout-insurance", { clear = true }),
        pattern = "*.dbout",
        callback = setup_dbout,
      })

      vim.api.nvim_create_user_command("SqlScratch", sql_scratch, {
        nargs = "?",
        complete = function() return connections() end,
        desc = "Open per-service SQL scratch buffer bound to a connection",
      })

      vim.api.nvim_create_user_command("SqlHistory", function(args)
        if args.args == "" then
          pick_service(open_history)
        else
          open_history(args.args)
        end
      end, {
        nargs = "?",
        complete = function() return connections() end,
        desc = "Open per-service executed-query history",
      })

      -- One-shot connectivity check: run `select 1` against a single service
      -- and show the result — nothing else gets opened or connected.
      vim.api.nvim_create_user_command("SqlPing", function(args)
        local run = function(service)
          if not service then return end
          require("lazy").load({ plugins = { "vim-dadbod" } })
          vim.cmd("DB " .. conn_url(service) .. " select 1 as ping")
        end
        if args.args == "" then
          pick_service(run)
        else
          run(args.args)
        end
      end, {
        nargs = "?",
        complete = function() return connections() end,
        desc = "Run select 1 against one connection to verify it",
      })

      vim.api.nvim_create_user_command("SqlDescribe", function(args)
        describe_table(args.args)
      end, {
        nargs = "?",
        desc = "Describe a table in the buffer's connection (default: table under cursor)",
      })

      vim.api.nvim_create_user_command("SqlTables", function()
        list_tables()
      end, {
        desc = "List all tables on the buffer's connection",
      })

      -- Rebuild the curated table lists behind the snowflake/databricks
      -- adapters (hf-db-catalogue-refresh from hf-workbench). Runs for a few
      -- minutes in the background; DBUI picks the new lists up on next expand.
      vim.api.nvim_create_user_command("SqlCatalogueRefresh", function()
        vim.notify("Refreshing db catalogue (hf-photon + snow)...", vim.log.levels.INFO)
        vim.system({ "hf-db-catalogue-refresh" }, { text = true }, function(out)
          vim.schedule(function()
            local log = vim.trim((out.stdout or "") .. "\n" .. (out.stderr or ""))
            if out.code == 0 then
              vim.notify("db catalogue refreshed\n" .. log, vim.log.levels.INFO)
            else
              vim.notify("db catalogue refresh failed\n" .. log, vim.log.levels.ERROR)
            end
          end)
        end)
      end, { desc = "Rebuild snowflake/databricks DBUI table lists" })

      vim.api.nvim_create_autocmd("User", {
        group = vim.api.nvim_create_augroup("dbui-sql-history", { clear = true }),
        pattern = "*DBExecutePost",
        callback = log_query,
      })

      -- Re-executing into an already-open dbout buffer replaces its content
      -- without a FileType/BufEnter event — re-render compactly after dadbod
      -- writes the new result.
      vim.api.nvim_create_autocmd("User", {
        group = vim.api.nvim_create_augroup("dbout-rerender", { clear = true }),
        pattern = "*DBExecutePost",
        callback = function(ev)
          local output = ev.match:match("^(.*)/DBExecutePost$")
          local buf = output and vim.fn.bufnr(output) or -1
          if buf < 0 then return end
          vim.schedule(function()
            if not vim.api.nvim_buf_is_valid(buf) then return end
            vim.api.nvim_buf_call(buf, setup_dbout)
          end)
        end,
      })

      vim.keymap.set("n", "<leader>D", "<cmd>DBUIToggle<CR>", { desc = "Toggle DBUI" })
      vim.keymap.set("x", "<leader>E", ":DB<CR>", { desc = "Execute SQL selection" })

      -- dadbod-ui maps <Leader>E buffer-locally to "edit bind parameters" in
      -- sql buffers; re-map it after its ftplugin so it runs the line instead.
      vim.api.nvim_create_autocmd("FileType", {
        group = vim.api.nvim_create_augroup("dbui-sql-run", { clear = true }),
        pattern = "sql",
        callback = function(ev)
          vim.keymap.set("n", "<leader>E", ":.DB<CR>", { buffer = ev.buf, desc = "Execute SQL line" })
          vim.keymap.set("n", "<leader>dt", function() describe_table("") end,
            { buffer = ev.buf, desc = "Describe table under cursor" })
          vim.keymap.set("n", "<leader>dT", list_tables,
            { buffer = ev.buf, desc = "List all tables on this connection" })
        end,
      })
    end,
  },
}
