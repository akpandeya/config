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
          local url = "http://localhost:8642"
          -- mdserve kills any server already on :8642 (it may be serving a
          -- different dir), so always just spawn it. In parallel, wait for
          -- the port then open the browser (initial sleep: don't hit the
          -- old server in the instant before mdserve's pkill lands).
          -- Nvim-spawned shells are login shells (~/.zshrc never runs), so
          -- source aliases.sh + fix PATH explicitly or mdserve is not found.
          local wait = ("(sleep 1; for i in {1..60}; do curl -sf -o /dev/null %s && open %s && exit 0; sleep 0.5; done) &"):format(url, url)
          local cmd = 'export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"'
            .. '; source "$HOME/code/personal/config/shell/aliases.sh" >/dev/null 2>&1'
            .. "; " .. wait .. "; mdserve " .. vim.fn.shellescape(dir)
          vim.fn.jobstart({ "zsh", "-lc", cmd }, { detach = true })
          vim.notify("mdserve: building " .. dir .. " — browser opens when ready")
        end,
        ft = "markdown",
        desc = "Markdown Browse site (mdserve)",
      },
    },
  },
}
