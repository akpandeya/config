return {
  {
    "lewis6991/gitsigns.nvim",
    event = { "BufReadPre", "BufNewFile" },
    config = function()
      local gitsigns = require("gitsigns")
      gitsigns.setup({
        on_attach = function(bufnr)
          local function map(mode, lhs, rhs, desc)
            vim.keymap.set(mode, lhs, rhs, { buffer = bufnr, silent = true, desc = desc })
          end

          -- Navigation between changes
          map("n", "]c", function() gitsigns.nav_hunk("next") end, "Next Git hunk")
          map("n", "[c", function() gitsigns.nav_hunk("prev") end, "Prev Git hunk")

          -- Actions
          map("n", "<leader>hp", gitsigns.preview_hunk, "Preview Git hunk")
          map("n", "<leader>hd", gitsigns.diffthis, "Diff this file")
        end,
      })
    end,
  },
}
