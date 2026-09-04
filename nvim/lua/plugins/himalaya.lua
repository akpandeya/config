return {
  {
    "pimalaya/himalaya-vim",
    cmd = { "Himalaya", "HimalayaAccount", "HimalayaAccountUnread", "HimalayaAccounts" },
    keys = {
      { "<leader>mw", "<cmd>HimalayaAccount work<cr>",     desc = "Mail: work" },
      { "<leader>mp", "<cmd>HimalayaAccount personal<cr>", desc = "Mail: personal" },
    },
    config = function()
      local function himalaya_flag(action, flag_name)
        local account = vim.fn["himalaya#domain#account#current"]()
        local folder  = vim.fn["himalaya#domain#folder#current"]()
        local id      = vim.fn.matchstr(vim.fn.getline("."), [[^|\s*\zs\d\+]])
        if id == "" then
          vim.notify("No envelope under cursor", vim.log.levels.WARN)
          return
        end
        local cmd = string.format(
          "himalaya flag %s --account %s --folder %s %s %s",
          action, vim.fn.shellescape(account), vim.fn.shellescape(folder), flag_name, id
        )
        vim.fn.jobstart(cmd, {
          on_exit = function(_, code)
            if code == 0 then
              vim.schedule(function() vim.cmd("Himalaya") end)
            else
              vim.schedule(function()
                vim.notify("himalaya flag " .. action .. " failed (exit " .. code .. ")", vim.log.levels.ERROR)
              end)
            end
          end,
        })
      end

      local function himalaya_filter(query)
        local account = vim.fn["himalaya#domain#account#current"]()
        local folder  = vim.fn["himalaya#domain#folder#current"]()
        vim.fn["himalaya#domain#email#list_with"](account, folder, 1, query or "")
      end

      vim.api.nvim_create_autocmd("FileType", {
        pattern = "himalaya-email-listing",
        callback = function(ev)
          local map = function(lhs, fn, desc)
            vim.keymap.set("n", lhs, fn, { buffer = ev.buf, silent = true, desc = desc })
          end
          map("R", function() himalaya_flag("add",    "seen")    end, "Mark read")
          map("U", function() himalaya_flag("remove", "seen")    end, "Mark unread")
          map("S", function() himalaya_flag("add",    "flagged") end, "Star")
          map("s", function() himalaya_flag("remove", "flagged") end, "Unstar")
          map("u", function() himalaya_filter("not flag seen") end, "Filter: unread")
          map("a", function() himalaya_filter("")              end, "Filter: all")
        end,
      })

      -- :HimalayaAccountUnread <account> — same as :HimalayaAccount, but
      -- chains the unread narrow onto the listing buffer's post-load
      -- FileType callback. Fixes the race where `+normal u` from the
      -- jarvis launcher fired before the buffer-local `u` keymap was
      -- mounted (the listing populates async, so the keystroke fell
      -- through to vim's default `undo`).
      vim.api.nvim_create_user_command("HimalayaAccountUnread", function(opts)
        vim.api.nvim_create_autocmd("FileType", {
          pattern = "himalaya-email-listing",
          once = true,
          callback = function()
            himalaya_filter("not flag seen")
          end,
        })
        vim.cmd("HimalayaAccount " .. opts.args)
      end, { nargs = 1 })
    end,
  },
}
