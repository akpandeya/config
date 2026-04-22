# starship

Matrix-green prompt that pairs with the kitty config in this repo.

Layout:

```
<pwd> 󱃾 <kube-context> (<namespace>)                         <pwd>  <branch> <git-status>  YYYY-MM-DD HH:MM
❯ █
```

- Left line 1: directory + kube context/namespace (kube section appears only
  when a kubeconfig context is active).
- Left line 2: prompt character (cursor sits here).
- Right side: directory + git branch and status + date/time. Git modules are
  omitted completely outside a git repository.

Git status glyphs (Nerd Font):
`` conflicted · `?` untracked · `!` modified · `+` staged · `»` renamed ·
`✘` deleted · `` stashed · `⇡N` ahead · `⇣N` behind · `⇕` diverged.

`setup-dev-env.sh` installs starship (via brew), symlinks
`starship.toml` to `~/.config/starship.toml`, and appends
`eval "$(starship init zsh)"` to `~/.zshrc` if it isn't there yet.
