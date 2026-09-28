return {
  {
    "coder/claudecode.nvim",
    dependencies = { "folke/snacks.nvim" },
    keys = {
      { "<leader>ac", "<cmd>ClaudeCode<cr>", desc = "Claude Code" },
    },
    cmd = "ClaudeCode",
    opts = {
      terminal_cmd = "claude --permission-mode bypassPermissions",
    },
    config = true,
  },
}
