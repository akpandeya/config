vim.g.mapleader = " "
vim.g.maplocalleader = " "

require("options")

local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not (vim.uv or vim.loop).fs_stat(lazypath) then
  vim.fn.system({
    "git", "clone", "--filter=blob:none", "--branch=stable",
    "https://github.com/folke/lazy.nvim.git", lazypath,
  })
end
vim.opt.rtp:prepend(lazypath)

local ai = require("ai-terminals")
vim.keymap.set("n", "<leader>ap", ai.copilot, { desc = "Copilot CLI" })
vim.keymap.set("n", "<leader>ag", ai.agy, { desc = "Gemini CLI" })

require("lazy").setup("plugins", {
  change_detection = { notify = false },
})

require("pyscratch")
