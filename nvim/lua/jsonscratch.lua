-- Per-project JSON scratch buffers + pretty-print formatting.
--
--   :JsonScratch [name]     picker over this project's scratches (most-recent
--                           first, "+ new scratch" last); creates scratch.json
--                           when none exist yet. With [name], opens
--                           stdpath("data")/json-scratch/<project-slug>/<name>.json
--                           directly.
--   :JsonScratchAll [p] [n] cross-project access: project picker (or [p],
--                           fuzzy-resolved), then that project's files.
--                           `:JsonScratchAll workb foo` → foo.json in workbench.
--   <leader>f / <leader>E   (json buffers / json-scratch buffers) pretty-print
--                           the buffer (or visual selection) in-place via jq
--                           (or python3 -m json.tool fallback).
--
-- Scratches autosave on BufLeave/FocusLost/exit.

local scratch_root = vim.fn.stdpath("data") .. "/json-scratch"

local function project_slug()
  local root = vim.fs.root(0, ".git") or vim.fn.getcwd()
  return vim.fs.basename(root) .. "-" .. vim.fn.sha256(root):sub(1, 6)
end

local function scratch_dir()
  return scratch_root .. "/" .. project_slug()
end

local function sanitize_name(name)
  name = vim.trim(name or ""):gsub("%.json$", "")
  if name == "" then return "scratch" end
  return name:gsub("[^%w%-_]", "_")
end

local function scratch_names(dir)
  dir = dir or scratch_dir()
  local names = {}
  for _, f in ipairs(vim.fn.globpath(dir, "*.json", false, true)) do
    table.insert(names, vim.fn.fnamemodify(f, ":t:r"))
  end
  table.sort(names)
  return names
end

local function open_scratch(name, dir)
  dir = dir or scratch_dir()
  vim.fn.mkdir(dir, "p")
  local path = dir .. "/" .. sanitize_name(name) .. ".json"
  vim.cmd.edit(vim.fn.fnameescape(path))
  vim.bo.filetype = "json"
end

-- Shared picker: telescope when available, vim.ui.select otherwise.
local function telescope_pick(title, entries, choose, preview)
  local ok, pickers = pcall(require, "telescope.pickers")
  if not ok then
    local items = {}
    for _, e in ipairs(entries) do table.insert(items, e.display) end
    vim.ui.select(items, { prompt = title .. ":" }, function(disp)
      if not disp then return end
      for _, e in ipairs(entries) do
        if e.display == disp then choose(e.value) return end
      end
    end)
    return
  end
  local finders = require("telescope.finders")
  local conf = require("telescope.config").values
  local actions = require("telescope.actions")
  local action_state = require("telescope.actions.state")
  pickers.new({}, {
    prompt_title = title,
    finder = finders.new_table({
      results = entries,
      entry_maker = function(e)
        return { value = e.value, display = e.display, ordinal = e.ordinal or e.display, path = e.path }
      end,
    }),
    sorter = conf.generic_sorter({}),
    previewer = preview and conf.file_previewer({}) or false,
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

local function prompt_new_scratch(dir)
  vim.ui.input({ prompt = "scratch name: ", default = "scratch" }, function(n)
    if not n then return end
    open_scratch(n == "" and "scratch" or n, dir)
  end)
end

-- Picker over one project's scratch files (newest first, "+ new scratch"
-- last). `dir` defaults to the current project.
local function pick_scratch(dir)
  dir = dir or scratch_dir()
  local files = vim.fn.globpath(dir, "*.json", false, true)
  local NEW = "+ new scratch"
  local entries = {}
  if #files == 0 then
    entries = {
      { display = "scratch (default)", value = "scratch" },
      { display = NEW, value = NEW },
    }
  else
    table.sort(files, function(a, b) return vim.fn.getftime(a) > vim.fn.getftime(b) end)
    for _, f in ipairs(files) do
      local name = vim.fn.fnamemodify(f, ":t:r")
      table.insert(entries, { display = name, value = name, path = f })
    end
    table.insert(entries, { display = NEW, value = NEW })
  end

  local function choose(sel)
    if not sel then return end
    if sel == NEW then
      prompt_new_scratch(dir)
    else
      open_scratch(sel, dir)
    end
  end

  telescope_pick("JsonScratch", entries, choose, #files > 0)
end

-- ---------------------------------------------------------- :JsonScratchAll

-- Projects under json-scratch/ that actually hold scratches (skips empty
-- dirs), newest-first by their most recent file.
local function project_dirs()
  local dirs = {}
  if vim.fn.isdirectory(scratch_root) == 0 then return dirs end
  for _, d in ipairs(vim.fn.readdir(scratch_root)) do
    local path = scratch_root .. "/" .. d
    if vim.fn.isdirectory(path) == 1 and #vim.fn.globpath(path, "*.json", false, true) > 0 then
      table.insert(dirs, { slug = d, path = path })
    end
  end
  local function newest(path)
    local t = 0
    for _, f in ipairs(vim.fn.globpath(path, "*.json", false, true)) do
      t = math.max(t, vim.fn.getftime(f))
    end
    return t
  end
  table.sort(dirs, function(a, b) return newest(a.path) > newest(b.path) end)
  return dirs
end

local function project_display(slug)
  return (slug:gsub("%-%x%x%x%x%x%x$", ""))
end

local function match_projects(query)
  query = query:lower()
  local dirs, exact, matches = project_dirs(), {}, {}
  for _, d in ipairs(dirs) do
    local display = project_display(d.slug):lower()
    if display == query or d.slug:lower() == query then
      table.insert(exact, d)
    elseif display:find(query, 1, true) or d.slug:lower():find(query, 1, true) then
      table.insert(matches, d)
    end
  end
  if #exact > 0 then return exact end
  return #matches > 0 and matches or dirs
end

local function pick_project()
  local dirs = project_dirs()
  if #dirs == 0 then
    pick_scratch()
    return
  end
  local entries = {}
  for _, d in ipairs(dirs) do
    table.insert(entries, { display = project_display(d.slug), value = d.slug })
  end
  telescope_pick("JsonScratch project", entries, function(slug)
    pick_scratch(scratch_root .. "/" .. slug)
  end, false)
end

local function jsonscratch_all(args)
  local fargs = args.fargs
  if #fargs == 0 then
    pick_project()
    return
  end
  local matches = match_projects(fargs[1])
  local function open_in(d, name)
    local dir = scratch_root .. "/" .. d.slug
    if name then
      open_scratch(name, dir)
    else
      pick_scratch(dir)
    end
  end
  if #matches == 1 then
    open_in(matches[1], fargs[2])
    return
  end
  local entries = {}
  for _, d in ipairs(matches) do
    table.insert(entries, { display = project_display(d.slug), value = d.slug })
  end
  telescope_pick("JsonScratch project", entries, function(slug)
    for _, d in ipairs(matches) do
      if d.slug == slug then open_in(d, fargs[2]) return end
    end
  end, false)
end

-- ---------------------------------------------------------- Pretty-printing

local function run_formatter(input)
  if vim.fn.executable("jq") == 1 then
    local res = vim.system({ "jq", "." }, { stdin = input, text = true }):wait()
    return res.code == 0, res.stdout, res.stderr
  end
  local res = vim.system({ "python3", "-m", "json.tool", "--indent", "2" }, { stdin = input, text = true }):wait()
  return res.code == 0, res.stdout, res.stderr
end

local function format_json(line1, line2)
  local buf = vim.api.nvim_get_current_buf()
  local start_idx = (line1 or 1) - 1
  local end_idx = line2 or vim.api.nvim_buf_line_count(buf)
  local lines = vim.api.nvim_buf_get_lines(buf, start_idx, end_idx, false)
  local text = table.concat(lines, "\n")
  if vim.trim(text) == "" then return end

  local ok, out, err = run_formatter(text)
  if not ok then
    vim.notify("json format failed:\n" .. vim.trim(err or "invalid JSON"), vim.log.levels.ERROR)
    return
  end

  local formatted = vim.split((out or ""):gsub("\n$", ""), "\n", { plain = true })
  local view = vim.fn.winsaveview()
  vim.api.nvim_buf_set_lines(buf, start_idx, end_idx, false, formatted)
  vim.fn.winrestview(view)
  if vim.api.nvim_buf_get_name(buf):find("/json%-scratch/") then
    vim.cmd("silent! update")
  end
end

-- ---------------------------------------------------------------- setup

local group = vim.api.nvim_create_augroup("json-scratch", { clear = true })

vim.api.nvim_create_user_command("JsonScratch", function(args)
  if #args.fargs == 0 then
    pick_scratch()
    return
  end
  open_scratch(args.fargs[1])
end, {
  nargs = "?",
  complete = function()
    return scratch_names()
  end,
  desc = "Open per-project JSON scratch ([name]; no arg = picker)",
})

vim.api.nvim_create_user_command("JsonScratchAll", jsonscratch_all, {
  nargs = "*",
  complete = function(_, cmdline)
    local fargs = vim.split(cmdline:match("JsonScratchAll%s+(.*)") or "", "%s+")
    if #fargs <= 1 then
      local names = {}
      for _, d in ipairs(project_dirs()) do
        table.insert(names, project_display(d.slug))
      end
      return names
    end
    local names = {}
    for _, d in ipairs(match_projects(fargs[1])) do
      vim.list_extend(names, scratch_names(scratch_root .. "/" .. d.slug))
    end
    return names
  end,
  desc = "Open a JSON scratch from any project ([project] [name]; no arg = project picker)",
})

vim.api.nvim_create_user_command("JsonFormat", function(args)
  if args.range > 0 then
    format_json(args.line1, args.line2)
  else
    format_json()
  end
end, {
  range = true,
  desc = "Pretty-print JSON buffer or visual selection",
})

vim.keymap.set("n", "<leader>dj", "<cmd>JsonScratch<CR>", { desc = "JsonScratch (current project)" })
vim.keymap.set("n", "<leader>dJ", "<cmd>JsonScratchAll<CR>", { desc = "JsonScratch: all projects" })

-- `:js` expands to :JsonScratch only when it is the whole cmdline.
vim.cmd([[
  cnoreabbrev <expr> js (getcmdtype() ==# ':' && getcmdline() ==# 'js') ? 'JsonScratch' : 'js'
]])

-- Format keymaps in JSON buffers (<leader>f and <leader>E).
vim.api.nvim_create_autocmd("FileType", {
  group = group,
  pattern = "json",
  callback = function(ev)
    vim.keymap.set("n", "<leader>f", function() format_json() end,
      { buffer = ev.buf, desc = "Pretty-print JSON" })
    vim.keymap.set("x", "<leader>f", ":JsonFormat<CR>",
      { buffer = ev.buf, silent = true, desc = "Pretty-print JSON selection" })
    vim.keymap.set("n", "<leader>E", function() format_json() end,
      { buffer = ev.buf, desc = "Pretty-print JSON" })
    vim.keymap.set("x", "<leader>E", ":JsonFormat<CR>",
      { buffer = ev.buf, silent = true, desc = "Pretty-print JSON selection" })
  end,
})

-- Autosave scratch buffers: they are real files, nothing should be lost.
vim.api.nvim_create_autocmd({ "BufLeave", "FocusLost" }, {
  group = group,
  pattern = "*/json-scratch/*.json",
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
      if name:find("/json%-scratch/") and vim.bo[buf].modified then
        vim.api.nvim_buf_call(buf, function() vim.cmd("silent! update") end)
      end
    end
  end,
})
