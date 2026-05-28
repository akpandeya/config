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


