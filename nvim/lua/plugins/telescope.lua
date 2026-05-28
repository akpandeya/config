return {
  {
    "nvim-telescope/telescope.nvim",
    cmd = "Telescope",
    dependencies = {
      "nvim-lua/plenary.nvim",
      {
        "nvim-telescope/telescope-fzf-native.nvim",
        build = "make",
        cond = function() return vim.fn.executable("make") == 1 end,
      },
    },
    keys = {
      { "<leader>ff", "<cmd>Telescope find_files<cr>",  desc = "Find files" },
      { "<leader>fg", "<cmd>Telescope live_grep<cr>",   desc = "Live grep" },
      { "<leader>fb", "<cmd>Telescope buffers<cr>",     desc = "Buffers" },
      { "<leader>fh", "<cmd>Telescope help_tags<cr>",   desc = "Help tags" },
      { "<leader>fr", "<cmd>Telescope oldfiles<cr>",    desc = "Recent files" },
      { "<leader>fs", "<cmd>Telescope lsp_document_symbols<cr>", desc = "Document symbols" },
      { "<leader>/",  "<cmd>Telescope current_buffer_fuzzy_find<cr>", desc = "Fuzzy in buffer" },
    },
    config = function()
      local telescope = require("telescope")
      telescope.setup({
        defaults = {
          path_display = { "truncate" },
          file_ignore_patterns = { "node_modules", "%.git/", "build/", "%.gradle/", "target/", "%.venv/", "venv/", "env/", "__pycache__/" },
          mappings = {
            i = {
              ["<C-j>"] = "move_selection_next",
              ["<C-k>"] = "move_selection_previous",
            },
          },
        },
        pickers = {
          find_files = { hidden = true },
        },
      })
      pcall(telescope.load_extension, "fzf")
    end,
  },
}
