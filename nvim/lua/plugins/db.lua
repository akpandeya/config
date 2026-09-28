-- Database tooling: vim-dadbod + UI + completion.
--
-- Connections come from the same pg_service.conf that drives `fpsql`
-- (shell/pg.sh) — parsed into g:dbs as `postgres://?service=<name>` URLs so
-- psql/libpq keeps resolving hosts/auth exactly like the CLI does.
--
--   :DBUI                 schema browser (<leader>D)
--   :SqlScratch [service] per-service scratch buffer (b:db pre-bound)
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

-- Populate g:dbs (DBUI connection list) from the service file.
-- NOTE: build the Lua table first and assign once — `vim.g.dbs = {}` becomes
-- a Vim *list* (empty-table ambiguity) and silently swallows string keys.
local function setup_connections()
  local dbs = {}
  for _, name in ipairs(services()) do
    dbs[name] = db_url(name)
  end
  if next(dbs) ~= nil then vim.g.dbs = dbs end
end

local function open_scratch(service)
  -- Ensure dadbod is loaded so b:db has an adapter behind it (SqlScratch is
  -- created in init() at startup, outside lazy.nvim's cmd stubs).
  require("lazy").load({ plugins = { "vim-dadbod" } })
  local dir = vim.fn.stdpath("data") .. "/sql-scratch"
  vim.fn.mkdir(dir, "p")
  local path = dir .. "/" .. service .. ".sql"
  vim.cmd.edit(vim.fn.fnameescape(path))
  vim.bo.filetype = "sql"
  vim.b.db = db_url(service)
end

local function sql_scratch(args)
  local service = args.args
  if service == "" then
    vim.ui.select(services(), { prompt = "Service:" }, function(sel)
      if sel then open_scratch(sel) end
    end)
  else
    open_scratch(service)
  end
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

      vim.api.nvim_create_user_command("SqlScratch", sql_scratch, {
        nargs = "?",
        complete = function() return services() end,
        desc = "Open per-service SQL scratch buffer bound to a pg service",
      })

      vim.keymap.set("n", "<leader>D", "<cmd>DBUIToggle<CR>", { desc = "Toggle DBUI" })
      vim.keymap.set("x", "<leader>E", ":DB<CR>", { desc = "Execute SQL selection" })
    end,
  },
}
