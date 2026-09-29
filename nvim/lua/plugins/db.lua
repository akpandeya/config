-- Database tooling: vim-dadbod + UI + completion.
--
-- Postgres connections come from the same pg_service.conf that drives
-- `fpsql` (shell/pg.sh) — parsed into g:dbs as `postgres://?service=<name>`
-- URLs so psql/libpq keeps resolving hosts/auth exactly like the CLI does.
-- Snowflake + Databricks are extra_connections: CLI-shelling dadbod adapters
-- (autoload/db/adapter/*.vim → `snow sql` / `hf-photon`), scratch + run only.
--
--   :DBUI                 schema browser (<leader>D)
--   :SqlScratch [service] per-service scratch buffer (b:db pre-bound)
--   :SqlHistory [service] log of every query executed against a service
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
-- (nvim/autoload/db/adapter/{snowflake,databricks}.vim). DBUI lists them but
-- there's no schema tree behind them — scratch + run only.
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

-- Result-buffer (dbout) niceties: long JSON cells otherwise mean endless
-- horizontal scroll in the table layout.
--   <Leader>R  toggle expanded layout (psql \x, built into dadbod-ui)
--   gj         open cell under cursor as pretty-printed JSON in a split
local function setup_dbout()
  vim.opt_local.wrap = true
  vim.opt_local.linebreak = true

  vim.keymap.set("n", "gj", function()
    vim.cmd('execute "normal vic"')
    vim.cmd("normal! y")
    local cell = vim.trim(vim.fn.getreg('"'))
    if cell == "" then return end

    local pretty = cell
    if vim.fn.executable("jq") == 1 then
      local out = vim.fn.system({ "jq", "." }, cell)
      if vim.v.shell_error == 0 then pretty = out:gsub("\n$", "") end
    end

    vim.cmd("vsplit")
    vim.cmd("enew")
    vim.bo.buftype = "nofile"
    vim.bo.bufhidden = "wipe"
    vim.bo.filetype = "json"
    vim.api.nvim_buf_set_lines(0, 0, -1, false, vim.split(pretty, "\n"))
  end, { buffer = true, desc = "Pretty-print cell JSON in split" })
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
      setup_connections()

      vim.api.nvim_create_autocmd("FileType", {
        group = vim.api.nvim_create_augroup("dbout-json", { clear = true }),
        pattern = "dbout",
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

      vim.api.nvim_create_autocmd("User", {
        group = vim.api.nvim_create_augroup("dbui-sql-history", { clear = true }),
        pattern = "*DBExecutePost",
        callback = log_query,
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
        end,
      })
    end,
  },
}
