return {
  {
    "MeanderingProgrammer/render-markdown.nvim",
    dependencies = { "nvim-treesitter/nvim-treesitter", "nvim-tree/nvim-web-devicons" },
    opts = {},
  },
  {
    "iamcco/markdown-preview.nvim",
    cmd = { "MarkdownPreviewToggle", "MarkdownPreview", "MarkdownPreviewStop" },
    ft = { "markdown" },
    build = "cd app && npm install",
    keys = {
      { "<leader>mp", "<cmd>MarkdownPreview<cr>", ft = "markdown", desc = "Markdown Preview" },
      {
        "<leader>mb",
        function()
          local dir = vim.fn.expand("%:p:h")
          vim.fn.jobstart({ "zsh", "-lc", "mdserve " .. vim.fn.shellescape(dir) }, { detach = true })
          vim.notify("mdserve: http://localhost:8642 (" .. dir .. ")")
        end,
        ft = "markdown",
        desc = "Markdown Browse site (mdserve)",
      },
    },
  },
}
