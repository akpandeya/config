return {
  {
    "hrsh7th/nvim-cmp",
    event = "InsertEnter",
    dependencies = {
      "hrsh7th/cmp-nvim-lsp",
      "hrsh7th/cmp-buffer",
      "hrsh7th/cmp-path",
      "L3MON4D3/LuaSnip",
      "saadparwaiz1/cmp_luasnip",
    },
    config = function()
      local cmp = require("cmp")
      local luasnip = require("luasnip")

      cmp.setup({
        snippet = {
          expand = function(args) luasnip.lsp_expand(args.body) end,
        },
        mapping = cmp.mapping.preset.insert({
          ["<C-y>"]     = cmp.mapping.complete(),
          ["<CR>"]      = cmp.mapping.confirm({ select = true }),
          ["<Tab>"] = cmp.mapping(function(fallback)
            if cmp.visible() then
              cmp.select_next_item()
            elseif luasnip.expand_or_jumpable() then
              luasnip.expand_or_jump()
            else
              fallback()
            end
          end, { "i", "s" }),
          ["<S-Tab>"] = cmp.mapping(function(fallback)
            if cmp.visible() then
              cmp.select_prev_item()
            elseif luasnip.jumpable(-1) then
              luasnip.jump(-1)
            else
              fallback()
            end
          end, { "i", "s" }),
        }),
        sources = cmp.config.sources({
          { name = "nvim_lsp" },
          { name = "luasnip" },
        }, {
          { name = "buffer" },
          { name = "path" },
        }),
      })

      -- SQL: complete tables/columns from the buffer's dadbod connection.
      -- db-catalogue is our own source for the CLI adapters (databricks /
      -- snowflake): their fully-qualified catalogue names never match
      -- vim-dadbod-completion's anchored filter when typing a fragment.
      cmp.register_source("db-catalogue", require("db-catalogue-cmp").new())
      cmp.setup.filetype({ "sql" }, {
        sources = cmp.config.sources({
          { name = "db-catalogue" },
          { name = "vim-dadbod-completion" },
        }, {
          { name = "buffer" },
        }),
      })

      -- Python: SQL completion only inside read_sql-style strings
      -- (treesitter gate in db-python.lua; backend from "# backend:" /
      -- :DBBackend, default sf). All backends come from the static
      -- catalogue (db-python-cmp) — vim-dadbod-completion can't be reused
      -- here: it hard-gates itself to sql filetypes.
      cmp.register_source("db-python-catalogue", require("db-python-cmp").new())
      cmp.setup.filetype({ "python" }, {
        sources = cmp.config.sources({
          { name = "nvim_lsp" },
          { name = "luasnip" },
          { name = "db-python-catalogue" },
        }, {
          { name = "buffer" },
          { name = "path" },
        }),
      })
    end,
  },
}
