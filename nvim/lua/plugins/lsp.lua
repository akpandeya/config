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
            [vim.diagnostic.severity.ERROR] = "",
            [vim.diagnostic.severity.WARN]  = "",
            [vim.diagnostic.severity.INFO]  = "",
            [vim.diagnostic.severity.HINT]  = "",
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
          map("gd",         vim.lsp.buf.definition,      "LSP: definition")
          map("gr",         vim.lsp.buf.references,      "LSP: references")
          map("gi",         vim.lsp.buf.implementation,  "LSP: implementation")
          map("K",          vim.lsp.buf.hover,           "LSP: hover")
          map("<leader>rn", vim.lsp.buf.rename,          "LSP: rename")
          map("<leader>ca", vim.lsp.buf.code_action,     "LSP: code action")
          map("[d",         vim.diagnostic.goto_prev,    "Diagnostic: prev")
          map("]d",         vim.diagnostic.goto_next,    "Diagnostic: next")
          map("<leader>f",  function() vim.lsp.buf.format({ async = true }) end, "LSP: format")
        end,
      })

      vim.lsp.enable({ "basedpyright", "kotlin_language_server" })
    end,
  },
}
