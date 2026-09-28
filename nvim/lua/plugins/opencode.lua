return {
  {
    "nickjvandyke/opencode.nvim",
    version = "*",
    keys = {
      { "<leader>ao", function() require("opencode").ask() end, mode = { "n", "x" }, desc = "Ask OpenCode" },
      { "<leader>aa", function() require("opencode").prompt() end, desc = "Open opencode prompt" },
      { "<leader>as", function() require("opencode").select() end, mode = { "n", "x" }, desc = "Select OpenCode action" },
    },
    config = function()
      vim.g.opencode_opts = {
        server = {
          start = function()
            vim.cmd("vsplit term://opencode --auto | wincmd p")
          end,
        },
      }
    end,
  },
}
