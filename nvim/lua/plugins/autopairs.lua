return {
  {
    "windwp/nvim-autopairs",
    event = "InsertEnter",
    config = function()
      -- check_ts: treesitter-aware pairing (e.g. no closing quote when the
      -- next char is a word char, so `don't` in comments stays sane).
      require("nvim-autopairs").setup({ check_ts = true })
      -- confirming a function/method in cmp appends ()
      require("cmp").event:on(
        "confirm_done",
        require("nvim-autopairs.completion.cmp").on_confirm_done()
      )
    end,
  },
}
