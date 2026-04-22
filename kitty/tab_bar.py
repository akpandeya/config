"""Custom kitty tab bar: tabs on the left, status (pwd + git + date/time) on the right.

The status is computed from the *active* window's current working directory, so it
reflects the shell you're looking at, not the kitty process cwd. Git output is
cached for a short time so running commands doesn't hammer `git` on every redraw.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime

from kitty.boss import get_boss
from kitty.fast_data_types import Screen
from kitty.tab_bar import (
    DrawData,
    ExtraData,
    TabBarData,
    as_rgb,
    draw_tab_with_powerline,
)

MATRIX_GREEN = 0x00FF41
MATRIX_GRAY = 0xB0B0B0
MATRIX_BLACK = 0x000000

# Nerd Font glyphs
ICON_FOLDER = ""        #
ICON_BRANCH = ""        #
ICON_CLOCK = ""         #
ICON_CALENDAR = ""      #
ICON_DIRTY = "!"
ICON_STAGED = "+"
ICON_UNTRACKED = "?"
ICON_CLEAN = ""         #
ICON_AHEAD = "⇡"         # ⇡
ICON_BEHIND = "⇣"        # ⇣

_git_cache: dict[str, tuple[float, str]] = {}
_GIT_TTL = 2.0  # seconds


def _active_cwd() -> str | None:
    boss = get_boss()
    w = boss.active_window
    if w is None:
        return None
    try:
        return w.cwd_of_child or None
    except Exception:
        return None


def _short_path(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    parts = path.split(os.sep)
    if len(parts) > 4:
        parts = parts[:1] + ["…"] + parts[-2:]
    return os.sep.join(parts)


def _git_info(cwd: str) -> str:
    now = time.monotonic()
    cached = _git_cache.get(cwd)
    if cached and now - cached[0] < _GIT_TTL:
        return cached[1]

    info = ""
    try:
        branch = subprocess.run(
            ["git", "-C", cwd, "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True, text=True, timeout=0.3,
        )
        if branch.returncode != 0:
            # Detached HEAD or not a repo. Try rev-parse for short SHA; if that
            # fails, it's not a repo at all — leave info empty.
            sha = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=0.3,
            )
            if sha.returncode != 0:
                _git_cache[cwd] = (now, "")
                return ""
            branch_name = sha.stdout.strip()
        else:
            branch_name = branch.stdout.strip()

        status = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v1", "--branch"],
            capture_output=True, text=True, timeout=0.3,
        )
        flags = []
        ahead = behind = 0
        untracked = modified = staged = 0
        if status.returncode == 0:
            for line in status.stdout.splitlines():
                if line.startswith("## "):
                    header = line[3:]
                    if "ahead " in header:
                        try:
                            ahead = int(header.split("ahead ")[1].split(",")[0].rstrip("]"))
                        except ValueError:
                            pass
                    if "behind " in header:
                        try:
                            behind = int(header.split("behind ")[1].split(",")[0].rstrip("]"))
                        except ValueError:
                            pass
                elif line.startswith("??"):
                    untracked += 1
                elif line:
                    x, y = line[0], line[1]
                    if x != " " and x != "?":
                        staged += 1
                    if y != " " and y != "?":
                        modified += 1
        if untracked:
            flags.append(f"{ICON_UNTRACKED}{untracked}")
        if modified:
            flags.append(f"{ICON_DIRTY}{modified}")
        if staged:
            flags.append(f"{ICON_STAGED}{staged}")
        if ahead:
            flags.append(f"{ICON_AHEAD}{ahead}")
        if behind:
            flags.append(f"{ICON_BEHIND}{behind}")
        if not flags:
            flags.append(ICON_CLEAN)

        info = f"{ICON_BRANCH} {branch_name} {' '.join(flags)}"
    except Exception:
        info = ""

    _git_cache[cwd] = (now, info)
    return info


def _build_status() -> str:
    cwd = _active_cwd()
    parts: list[str] = []

    if cwd:
        parts.append(f"{ICON_FOLDER} {_short_path(cwd)}")
        git = _git_info(cwd)
        if git:
            parts.append(git)

    now = datetime.now()
    parts.append(f"{ICON_CALENDAR} {now.strftime('%Y-%m-%d')}")
    parts.append(f"{ICON_CLOCK} {now.strftime('%H:%M')}")

    return "  ".join(parts)


def _draw_status(screen: Screen, tab_bar_width: int) -> None:
    text = "  " + _build_status() + "  "
    cells = len(text)
    col = max(screen.cursor.x, tab_bar_width - cells)
    # pad between last tab and the status so the bar looks contiguous
    screen.cursor.bg = as_rgb(MATRIX_BLACK)
    screen.cursor.fg = as_rgb(MATRIX_GRAY)
    while screen.cursor.x < col:
        screen.draw(" ")
    screen.cursor.fg = as_rgb(MATRIX_GREEN)
    screen.cursor.bold = True
    screen.draw(text)
    screen.cursor.bold = False


def draw_tab(
    draw_data: DrawData,
    screen: Screen,
    tab: TabBarData,
    before: int,
    max_title_length: int,
    index: int,
    is_last: bool,
    extra_data: ExtraData,
) -> int:
    end = draw_tab_with_powerline(
        draw_data, screen, tab, before, max_title_length, index, is_last, extra_data
    )
    if is_last:
        _draw_status(screen, screen.columns)
    return end
