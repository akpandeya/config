return {
  {
    "folke/which-key.nvim",
    event = "VeryLazy",
    opts = {
      preset = "modern",
      spec = {
        { "<leader>f", group = "Find / Telescope" },
        { "<leader>c", group = "Cheatsheet / Code" },
        { "<leader>h", group = "Git Hunk" },
        { "<leader>m", group = "Mail" },
        { "<leader>r", group = "Rename" },
      },
    },
    keys = {
      {
        "<leader>?",
        function()
          require("which-key").show({ global = false })
        end,
        desc = "Buffer Keymaps",
      },
    },
  },
}
