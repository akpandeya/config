return {
  {
    "folke/tokyonight.nvim",
    lazy = false,
    priority = 1000, -- Load this first so it styles the UI during startup
    config = function()
      require("tokyonight").setup({
        style = "storm", -- Options: storm, moon, night, day
        light_style = "day",
        transparent = true,
        terminal_colors = true,
        styles = {
          comments = { italic = true },
          keywords = { italic = true },
          functions = {},
          variables = {},
          sidebars = "dark", -- Style for sidebar panels like neo-tree
          floats = "dark", -- Style for popups/hover documentation
        },
      })

      -- Set the colorscheme
      vim.cmd("colorscheme tokyonight-storm")
    end,
  },
}
