local function terminal(cmd)
  return function()
    local wins = vim.tbl_filter(function(w)
      local name = vim.api.nvim_buf_get_name(vim.api.nvim_win_get_buf(w))
      return vim.bo[vim.api.nvim_win_get_buf(w)].buftype == "terminal" and name:match(cmd) ~= nil
    end, vim.api.nvim_list_wins())
    if #wins > 0 then
      vim.api.nvim_set_current_win(wins[1])
      return
    end
    vim.cmd("botright 15split | term " .. cmd)
  end
end

return {
  cc = terminal("claude"),
  copilot = terminal("copilot"),
  agy = terminal("agy"),
}
