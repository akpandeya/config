# kitty

Matrix-themed kitty config: black background, green text, tabs on the **bottom-left**
(active = green, inactive = dim gray) with a custom status on the **bottom-right**
showing current pwd, git branch with status icons (absent when not in a git repo),
date, and time.

## Files

- `kitty.conf` — colors, font, tab bar configuration.
- `tab_bar.py` — custom renderer that draws the right-side status. Called
  because `kitty.conf` sets `tab_bar_style custom`.

Requires the `JetBrainsMono Nerd Font` so the glyphs render; installed via
`brew-packages.txt` by `setup-dev-env.sh`.

## Install

`setup-dev-env.sh` symlinks both files into `~/.config/kitty/`. If a real file
already exists at either path it is moved to `<path>.backup.<timestamp>` first.

Restart kitty after linking. The status refreshes every second (kitty's default
tab-bar redraw interval).

## Status glyphs

`` branch · `` clean · `!N` modified · `+N` staged · `?N` untracked ·
`⇡N` ahead · `⇣N` behind.
