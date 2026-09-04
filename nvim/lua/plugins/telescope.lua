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
      { "<leader>fg", "<cmd>GrepFiles<cr>",             desc = "Files containing string" },
      { "<leader>fG", "<cmd>Telescope live_grep<cr>",   desc = "Live grep (lines)" },
      { "<leader>fb", "<cmd>Telescope buffers<cr>",     desc = "Buffers" },
      { "<leader>fh", "<cmd>Telescope help_tags<cr>",   desc = "Help tags" },
      { "<leader>fr", "<cmd>Telescope oldfiles<cr>",    desc = "Recent files" },
      { "<leader>fs", "<cmd>Telescope lsp_document_symbols<cr>", desc = "Document symbols" },
      { "<leader>/",  "<cmd>Telescope current_buffer_fuzzy_find<cr>", desc = "Fuzzy in buffer" },
      { "<leader>fc", "<cmd>Telescope commands<cr>", desc = "Find commands" },
      { "<leader>fk", "<cmd>Telescope keymaps<cr>",  desc = "Find keymaps" },
    },
    config = function()
      local telescope = require("telescope")

      -- File-level grep: list each file that contains the string once (via `rg -l`),
      -- with a scrolling preview. Open the file, then use `/` to jump to the match.
      local function grep_files_with_matches(opts)
        opts = opts or {}
        vim.ui.input({ prompt = "Files containing: " }, function(query)
          if not query or query == "" then return end
          local pickers = require("telescope.pickers")
          local finders = require("telescope.finders")
          local conf = require("telescope.config").values
          pickers.new(opts, {
            prompt_title = "Files containing '" .. query .. "'",
            finder = finders.new_oneshot_job(
              { "rg", "--files-with-matches", "--color=never", "--", query },
              opts
            ),
            sorter = conf.file_sorter(opts),
            previewer = conf.file_previewer(opts),
          }):find()
        end)
      end

      vim.api.nvim_create_user_command("GrepFiles", function()
        grep_files_with_matches()
      end, {})

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
