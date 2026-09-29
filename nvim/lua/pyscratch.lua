-- Per-project python scratch buffers + DB backend binding for python files.
--
--   :PyScratch              picker over this project's scratches (most-recent
--                           first, "+ new scratch" last); creates scratch.py
--                           when none exist yet
--   :PyScratch [t] [name]   open stdpath("data")/py-scratch/<project-slug>/
--                           <name>.py; [t] picks the template for NEW files:
--                             plain  main() + __main__ block (default)
--                             sql    + read_sql/duck imports and usage notes
--                             blank  empty file
--                           Examples: :PyScratch sql      → sql.py (sql)
--                                     :PyScratch sql foo  → foo.py (sql)
--                                     :PyScratch foo      → foo.py (plain)
--                           Existing files always open as-is.
--   :DBBackend [name]       set b:db_backend for this buffer (sf | dbx |
--                           pg:<service> | bare pg service); picker when no
--                           arg. Persistent alternative: "# backend:" line.
--   <leader>E               (py-scratch buffers) save + run with the shared
--                           venv in a terminal split; focus returns to the
--                           scratch, q closes the output split.
--
-- Scratches run against one shared venv (stdpath("data")/py-scratch-venv,
-- created on first use): pandas/duckdb/psycopg/databricks-sql-connector
-- preinstalled, and a .pth entry makes `import db` (hf-workbench) resolve
-- with no sys.path hacks. A pyrightconfig.json per scratch dir points
-- basedpyright at the same venv, so LSP imports and types resolve for real.
-- Scratches autosave on BufLeave/FocusLost/exit.
--
-- pg backends also set b:db = postgres://?service=<svc> (and force-load
-- vim-dadbod) so `:DB` works in python buffers too — e.g. visual-select a
-- SQL string and run it. SQL completion in python strings is handled by
-- db-python-cmp (catalogue files), not vim-dadbod-completion.

local resolver = require("db-python")

local scratch_root = vim.fn.stdpath("data") .. "/py-scratch"
local venv = vim.fn.stdpath("data") .. "/py-scratch-venv"
local venv_python = venv .. "/bin/python"

local function workbench_bin()
  return (vim.env.HF_WORKBENCH_ROOT or (vim.env.HOME .. "/code/work/hf-workbench")) .. "/bin"
end

-- Keep in sync with db.py's PEP723 dependencies.
local VENV_DEPS = {
  "pandas", "duckdb", "psycopg[binary]",
  "databricks-sql-connector==3.1.2", "numpy<2", "urllib3==2.7.0",
}

local TEMPLATES = {
  plain = [[def main():
    pass


if __name__ == "__main__":
    main()
]],
  sql = [[# backend: sf
from db import read_sql, duck

# read_sql(sql, backend) -> DataFrame
#   backends: "sf" (snowflake, default) | "dbx" (databricks) | "pg:<service>"
#   table (+column for pg) completion works inside read_sql("...") — the
#   backend comes from the "# backend:" line above, or :DBBackend.
#
# duck(**dfs) combines backends via DuckDB:
#   con = duck(sf=df1, pg=df2)
#   con.sql("select ... from sf join pg using (id)").df()
#
# <leader>E runs this file in a terminal split (q closes the output).

def main():
    df = read_sql("select 1 as x", "sf")
    print(df)
    # duckdb view of the same df — combine with other backends the same way:
    print(duck(sf=df).sql("select * from sf").df())


if __name__ == "__main__":
    main()
]],
  blank = "",
}

-- Shared venv: create in the background on first use.
local function ensure_venv()
  if vim.fn.executable(venv_python) == 1 then return end
  vim.notify("py-scratch: creating shared venv (first use only)...", vim.log.levels.INFO)
  vim.system({ "uv", "venv", "--python", "3.12", venv }, { text = true }, function(vout)
    if vout.code ~= 0 then
      vim.schedule(function()
        vim.notify("py-scratch: uv venv failed\n" .. (vout.stderr or ""), vim.log.levels.ERROR)
      end)
      return
    end
    local install = { "uv", "pip", "install", "--quiet", "--python", venv_python }
    vim.list_extend(install, VENV_DEPS)
    vim.system(install, { text = true }, function(pout)
      vim.schedule(function()
        if pout.code ~= 0 then
          vim.notify("py-scratch: dep install failed\n" .. (pout.stderr or ""), vim.log.levels.ERROR)
          return
        end
        -- .pth entry so `import db` resolves inside the venv (and for
        -- basedpyright, which reads site-packages .pth files).
        local sp = vim.trim(vim.fn.system({ venv_python, "-c", "import site; print(site.getsitepackages()[0])" }))
        local fd = io.open(sp .. "/hf-workbench.pth", "w")
        if fd then
          fd:write(workbench_bin() .. "\n")
          fd:close()
        end
        vim.notify("py-scratch: shared venv ready", vim.log.levels.INFO)
      end)
    end)
  end)
end

-- Point basedpyright at the shared venv. pyrightconfig.json is an lspconfig
-- root marker, so the scratch dir becomes its own LSP workspace.
local function ensure_pyrightconfig(dir)
  local path = dir .. "/pyrightconfig.json"
  if vim.fn.filereadable(path) == 1 then return end
  local fd = io.open(path, "w")
  if not fd then return end
  fd:write(vim.json.encode({
    venvPath = vim.fn.fnamemodify(venv, ":h"),
    venv = vim.fn.fnamemodify(venv, ":t"),
    reportMissingTypeStubs = false,
  }))
  fd:write("\n")
  fd:close()
end

local function project_slug()
  local root = vim.fs.root(0, ".git") or vim.fn.getcwd()
  return vim.fs.basename(root) .. "-" .. vim.fn.sha256(root):sub(1, 6)
end

local function scratch_dir()
  return scratch_root .. "/" .. project_slug()
end

local function scratch_names()
  local names = {}
  for _, f in ipairs(vim.fn.globpath(scratch_dir(), "*.py", false, true)) do
    table.insert(names, vim.fn.fnamemodify(f, ":t:r"))
  end
  table.sort(names)
  return names
end

local function open_scratch(name, template)
  local dir = scratch_dir()
  vim.fn.mkdir(dir, "p")
  ensure_venv()
  ensure_pyrightconfig(dir)
  local path = dir .. "/" .. name .. ".py"
  local is_new = vim.fn.filereadable(path) == 0
  vim.cmd.edit(vim.fn.fnameescape(path))
  if is_new and template and template ~= "blank" then
    vim.api.nvim_buf_set_lines(0, 0, -1, false, vim.split(TEMPLATES[template], "\n", { plain = true }))
    vim.cmd("silent! update")
  end
end

-- ---------------------------------------------------------------- :PyScratch

-- :PyScratch [template] [name] — first template-shaped arg wins, the next
-- arg is the file name.
local function parse_args(fargs)
  local template, name = "plain", nil
  if TEMPLATES[fargs[1]] then
    template = fargs[1]
    name = fargs[2]
  else
    name = fargs[1]
  end
  if not name then
    name = template == "sql" and "sql" or "scratch"
  end
  return template, name
end

local function pick_scratch()
  local files = vim.fn.globpath(scratch_dir(), "*.py", false, true)
  if #files == 0 then
    open_scratch("scratch", "plain")
    return
  end
  table.sort(files, function(a, b) return vim.fn.getftime(a) > vim.fn.getftime(b) end)
  local NEW = "+ new scratch"
  local items = {}
  for _, f in ipairs(files) do
    table.insert(items, vim.fn.fnamemodify(f, ":t:r"))
  end
  table.insert(items, NEW)

  local function choose(sel)
    if not sel then return end
    if sel == NEW then
      vim.ui.input({ prompt = "scratch name: " }, function(n)
        if n and n ~= "" then open_scratch(n, "plain") end
      end)
    else
      open_scratch(sel, "plain")
    end
  end

  local ok, pickers = pcall(require, "telescope.pickers")
  if not ok then
    vim.ui.select(items, { prompt = "PyScratch:" }, choose)
    return
  end
  local finders = require("telescope.finders")
  local conf = require("telescope.config").values
  local actions = require("telescope.actions")
  local action_state = require("telescope.actions.state")
  pickers.new({}, {
    prompt_title = "PyScratch",
    finder = finders.new_table({ results = items }),
    sorter = conf.generic_sorter({}),
    previewer = false,
    attach_mappings = function(prompt_bufnr, _)
      actions.select_default:replace(function()
        local sel = action_state.get_selected_entry().value
        actions.close(prompt_bufnr)
        choose(sel)
      end)
      return true
    end,
  }):find()
end

-- ---------------------------------------------------------------- b:db sync

local dadbod_loaded = false

local function sync_b_db(buf)
  buf = buf or vim.api.nvim_get_current_buf()
  if vim.bo[buf].buftype ~= "" then return end -- never touch terminal/special buffers
  local kind, service = resolver.backend_kind(resolver.backend_for(buf))
  if kind == "pg" and service then
    if not dadbod_loaded then
      pcall(require("lazy").load, { plugins = { "vim-dadbod" } })
      dadbod_loaded = true
    end
    vim.b[buf].db = "postgres://?service=" .. service
  elseif vim.b[buf].db then
    vim.b[buf].db = nil
  end
end

-- ---------------------------------------------------------------- :DBBackend

local function backends()
  local list = { "sf", "dbx" }
  for _, s in ipairs(resolver.pg_services()) do
    table.insert(list, "pg:" .. s)
  end
  return list
end

local function set_backend(name)
  vim.b.db_backend = name
  sync_b_db(0)
  vim.notify("backend: " .. name, vim.log.levels.INFO)
end

local function pick_backend()
  local ok, pickers = pcall(require, "telescope.pickers")
  if not ok then
    vim.ui.select(backends(), { prompt = "Backend:" }, function(sel)
      if sel then set_backend(sel) end
    end)
    return
  end
  local finders = require("telescope.finders")
  local conf = require("telescope.config").values
  local actions = require("telescope.actions")
  local action_state = require("telescope.actions.state")
  pickers.new({}, {
    prompt_title = "Backend",
    finder = finders.new_table({ results = backends() }),
    sorter = conf.generic_sorter({}),
    previewer = false,
    attach_mappings = function(prompt_bufnr, _)
      actions.select_default:replace(function()
        local sel = action_state.get_selected_entry().value
        actions.close(prompt_bufnr)
        set_backend(sel)
      end)
      return true
    end,
  }):find()
end

-- ---------------------------------------------------------------- setup

local group = vim.api.nvim_create_augroup("py-db", { clear = true })

vim.api.nvim_create_user_command("PyScratch", function(args)
  if #args.fargs == 0 then
    pick_scratch()
    return
  end
  local template, name = parse_args(args.fargs)
  open_scratch(name, template)
end, {
  nargs = "*",
  complete = function()
    local items = { "plain", "sql", "blank" }
    vim.list_extend(items, scratch_names())
    return items
  end,
  desc = "Open per-project python scratch ([template] [name]; no arg = picker)",
})

vim.api.nvim_create_user_command("DBBackend", function(args)
  if args.args ~= "" then
    set_backend(args.args)
  else
    pick_backend()
  end
end, {
  nargs = "?",
  complete = backends,
  desc = "Set DB backend for this python buffer (completion + b:db)",
})

-- Keep b:db in sync with the resolved backend on every python buffer.
vim.api.nvim_create_autocmd("FileType", {
  group = group,
  pattern = "python",
  callback = function(ev) sync_b_db(ev.buf) end,
})
vim.api.nvim_create_autocmd({ "BufEnter", "TextChanged", "TextChangedI" }, {
  group = group,
  pattern = "*.py",
  callback = function(ev) sync_b_db(ev.buf) end,
})

-- Autosave scratch buffers: they are real files, nothing should be lost.
vim.api.nvim_create_autocmd({ "BufLeave", "FocusLost" }, {
  group = group,
  pattern = "*/py-scratch/*.py",
  callback = function(ev)
    if vim.bo[ev.buf].modified then
      vim.api.nvim_buf_call(ev.buf, function() vim.cmd("silent! update") end)
    end
  end,
})
vim.api.nvim_create_autocmd("VimLeavePre", {
  group = group,
  callback = function()
    for _, buf in ipairs(vim.api.nvim_list_bufs()) do
      local name = vim.api.nvim_buf_get_name(buf)
      if name:find("/py%-scratch/") and vim.bo[buf].modified then
        vim.api.nvim_buf_call(buf, function() vim.cmd("silent! update") end)
      end
    end
  end,
})

-- <leader>E runs the scratch with the shared venv (mirrors the sql-buffer
-- execute mapping). 12new — NOT 12split: splitting without a file would
-- reuse the scratch buffer and let termopen() hijack it (ft=python sticks,
-- basedpyright attaches to the terminal, and the scratch "disappears").
vim.api.nvim_create_autocmd("BufEnter", {
  group = group,
  pattern = "*/py-scratch/*.py",
  callback = function(ev)
    vim.keymap.set("n", "<leader>E", function()
      if vim.fn.executable(venv_python) == 0 then
        ensure_venv()
        vim.notify("py-scratch: venv is still being created, try again shortly", vim.log.levels.WARN)
        return
      end
      vim.cmd("silent! update")
      local scratch_path = vim.api.nvim_buf_get_name(ev.buf)
      vim.cmd("botright 12new")
      local out_buf = vim.api.nvim_get_current_buf()
      vim.fn.termopen({ venv_python, scratch_path })
      vim.keymap.set("n", "q", "<cmd>close<CR>", { buffer = out_buf, desc = "Close output" })
      vim.cmd("wincmd p") -- focus returns to the scratch
    end, { buffer = ev.buf, desc = "Run scratch with shared venv" })
  end,
})
