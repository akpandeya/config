# 1Password CLI

- Use the `op` CLI only when explicitly asked to fetch or use a secret, and
  expect the user to authenticate each time (biometric prompt). Never run `op`
  in the background or in batch loops.
- Never print secret values into the conversation, files, or logs. Prefer
  injecting secrets without displaying them:
  - `op run -- <cmd>` (resolves `op://` refs into the command's env), or
  - `op read "op://..." | <consume directly>` (pipe, don't echo), or
  - pass `op://` references and let the consuming tool resolve them.
- After any `op` use, do not echo, summarize, or commit the resolved value.
  Refer to it by its `op://` reference instead.
- If a secret value ever appears in tool output anyway, tell the user
  immediately so they can decide whether to rotate it.

# Command output

Command output here is condensed to save tokens, keeping every signal and
dropping costly noise. Treat it as the complete result: run commands
normally, and batch related commands into one call to avoid extra turns.
Truncated results state their recovery path in their own output. Re-run a
command as `rtk bypass <cmd>` only when its result is unusable: empty when
output was clearly expected, contradicting its exit code, or garbled.
