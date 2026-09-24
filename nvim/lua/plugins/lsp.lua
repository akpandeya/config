return {
  {
    "neovim/nvim-lspconfig",
    event = { "BufReadPre", "BufNewFile" },
    dependencies = {
      "williamboman/mason-lspconfig.nvim",
      "hrsh7th/cmp-nvim-lsp",
    },
    config = function()
      local capabilities = require("cmp_nvim_lsp").default_capabilities()

      vim.diagnostic.config({
        signs = {
          text = {
            [vim.diagnostic.severity.ERROR] = "✘",
            [vim.diagnostic.severity.WARN]  = "▲",
            [vim.diagnostic.severity.INFO]  = "ℹ",
            [vim.diagnostic.severity.HINT]  = "󰌵",
          },
        },
        virtual_text = { spacing = 2, prefix = "●" },
        severity_sort = true,
      })

      vim.lsp.config("*", { capabilities = capabilities })

      vim.api.nvim_create_autocmd("LspAttach", {
        callback = function(ev)
          local map = function(lhs, rhs, desc)
            vim.keymap.set("n", lhs, rhs, { buffer = ev.buf, silent = true, desc = desc })
          end
          map("gd",         "<cmd>Telescope lsp_definitions<cr>",      "LSP: definition")
          map("gr",         "<cmd>Telescope lsp_references<cr>",       "LSP: references")
          map("gi",         "<cmd>Telescope lsp_implementations<cr>",  "LSP: implementation")
          map("K",          vim.lsp.buf.hover,                         "LSP: hover")
          map("<leader>rn", vim.lsp.buf.rename,                        "LSP: rename")
          map("<leader>ca", vim.lsp.buf.code_action,                   "LSP: code action")
          map("[d",         vim.diagnostic.goto_prev,                  "Diagnostic: prev")
          map("]d",         vim.diagnostic.goto_next,                  "Diagnostic: next")
          map("<leader>f",  function() vim.lsp.buf.format({ async = true }) end, "LSP: format")
        end,
      })

      vim.lsp.config("kotlin", {
        cmd = { "kotlin-lsp", "--stdio" },
        filetypes = { "kotlin" },
        root_markers = { "settings.gradle.kts", "build.gradle.kts", "pom.xml", ".git" },
        single_file_support = false,
      })

      vim.lsp.enable({ "basedpyright", "kotlin", "marksman" })
    end,
  },
}
