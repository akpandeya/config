return {
  {
    "nvim-neo-tree/neo-tree.nvim",
    branch = "v3.x",
    dependencies = {
      "nvim-lua/plenary.nvim",
      "nvim-tree/nvim-web-devicons", -- styled icons for files and folders
      "MunifTanjim/nui.nvim", -- UI component library dependency
    },
    keys = {
      { "<leader>e", "<cmd>Neotree toggle<cr>", desc = "Toggle Explorer" },
    },
    opts = {
      close_if_last_window = true, -- Automatically close if the explorer is the only window left
      filesystem = {
        filtered_items = {
          visible = true, -- Show gitignored/hidden files but render them slightly faded
          hide_dotfiles = false,
          hide_gitignored = false,
        },
        follow_current_file = {
          enabled = true, -- Automatically expand directories and focus the active file
        },
        use_libuv_file_watcher = true, -- Auto-refresh when files change on disk
      },
    },
  },
}
