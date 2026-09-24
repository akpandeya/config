-- Disable netrw to let oil.nvim handle directory browsing
vim.g.loaded_netrw = 1
vim.g.loaded_netrwPlugin = 1

vim.opt.number = true
vim.opt.relativenumber = true
vim.opt.expandtab = true
vim.opt.shiftwidth = 2
vim.opt.tabstop = 2
vim.opt.smartindent = true
vim.opt.ignorecase = true
vim.opt.smartcase = true
vim.opt.termguicolors = true
vim.opt.signcolumn = "yes"
vim.opt.clipboard = "unnamedplus"
vim.opt.scrolloff = 5
vim.opt.updatetime = 250
vim.opt.undofile = true
vim.opt.splitbelow = true
vim.opt.splitright = true
vim.opt.cursorline = true
vim.opt.inccommand = "split"
vim.opt.timeoutlen = 300

-- Clear search highlights on pressing Escape in normal mode
vim.keymap.set("n", "<Esc>", "<cmd>nohlsearch<CR>", { silent = true, desc = "Clear search highlights" })

-- Seamless window navigation (without Ctrl-w)
vim.keymap.set("n", "<C-h>", "<C-w>h", { desc = "Move to left window" })
vim.keymap.set("n", "<C-j>", "<C-w>j", { desc = "Move to lower window" })
vim.keymap.set("n", "<C-k>", "<C-w>k", { desc = "Move to upper window" })
vim.keymap.set("n", "<C-l>", "<C-w>l", { desc = "Move to right window" })

-- Keymaps to open the cheatsheet
vim.keymap.set("n", "<leader>ch", function()
  vim.cmd("edit " .. vim.fn.stdpath("config") .. "/CHEATSHEET.md")
end, { desc = "Open Cheatsheet in Current Window" })

vim.keymap.set("n", "<leader>cr", function()
  vim.cmd("botright vsplit " .. vim.fn.stdpath("config") .. "/CHEATSHEET.md")
end, { desc = "Open Cheatsheet in Right Split" })

vim.keymap.set("n", "<leader>cb", function()
  vim.cmd("botright split " .. vim.fn.stdpath("config") .. "/CHEATSHEET.md")
end, { desc = "Open Cheatsheet in Bottom Split" })


