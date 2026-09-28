-- Per-project sessions: auto-save on exit, auto-restore on open.
--
-- Sessions are keyed by cwd (in stdpath("data")/sessions), so launching nvim
-- in a project you've used before restores its tabs, splits and buffers with
-- no manual saving.
--
--   <leader>qs   restore session for current dir
--   <leader>qS   pick a session to restore
--   <leader>ql   restore the last session
--   <leader>qd   stop saving for this session (vanilla exit)

return {
  "folke/persistence.nvim",
  event = "BufReadPre",
  keys = {
    { "<leader>qs", function() require("persistence").load() end, desc = "Session: Restore" },
    { "<leader>qS", function() require("persistence").select() end, desc = "Session: Pick" },
    { "<leader>ql", function() require("persistence").load({ last = true }) end, desc = "Session: Last" },
    { "<leader>qd", function() require("persistence").stop() end, desc = "Session: Stop" },
  },
  opts = {},
}
