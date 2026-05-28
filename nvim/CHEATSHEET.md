# ⚡ Neovim & Vim Cheatsheet

Your `<leader>` key is mapped to the **Spacebar** (` `).

### 📖 Opening this Cheatsheet:
*   **`Space + c + h`** (`<leader>ch`) $\rightarrow$ Open in the current window.
*   **`Space + c + r`** (`<leader>cr`) $\rightarrow$ Open in a **vertical split (on the right)**.
*   **`Space + c + b`** (`<leader>cb`) $\rightarrow$ Open in a **horizontal split (at the bottom)**.

---

## 🔍 1. Project Navigation (Telescope)
| Keybinding | Action | Description |
|---|---|---|
| `<leader>ff` (`Space + f + f`) | **Find Files** | Fuzzy search all files in the project |
| `<leader>fg` (`Space + f + g`) | **Live Grep** | Search for text across all files |
| `<leader>fb` (`Space + f + b`) | **Buffers** | List and switch between open files |
| `<leader>fr` (`Space + f + r`) | **Recent Files** | Show recently opened files |
| `<leader>fs` (`Space + f + s`) | **Document Symbols** | Find classes/methods/variables in current file |
| `<leader>/` (`Space + /`) | **Fuzzy Search** | Search text inside the active buffer |
| `<leader>fc` (`Space + f + c`) | **Find Commands** | Search available Vim and plugin commands |
| `<leader>fk` (`Space + f + k`) | **Find Keymaps** | Search active key combinations |
| `<leader>e` (`Space + e`) | **Toggle Explorer** | Open/close the sidebar file tree (Neo-tree) |
| `Ctrl + j` / `Ctrl + k` | **Telescope Nav** | Move down/up the results list (inside Telescope) |
| `Ctrl + v` | **Vert Split Open** | Open selected file in a vertical split (on the right) |
| `Ctrl + x` | **Horiz Split Open**| Open selected file in a horizontal split (on bottom) |
| `Ctrl + t` | **Tab Open** | Open selected file in a new editor tab |

---

## 🗂️ 2. Splitting Views (Window Management)
All split movements start with `Ctrl + w`.

| Command / Key | Action | Description |
|---|---|---|
| `:vsp` / `:vsplit` | **Vertical Split** | Split window side-by-side |
| `:sp` / `:split` | **Horizontal Split** | Split window top-to-bottom |
| `Ctrl + w, h` | **Move Left** | Move focus to the left window split |
| `Ctrl + w, l` | **Move Right** | Move focus to the right window split |
| `Ctrl + w, k` | **Move Up** | Move focus to the upper window split |
| `Ctrl + w, j` | **Move Down** | Move focus to the lower window split |
| `Ctrl + w, c` / `:q` | **Close Split** | Close the current active split |
| `Ctrl + w, o` | **Maximize** | Close all other splits except the active one |
| `Ctrl + w, >` / `<` | **Resize Width** | Increase / decrease window width |
| `Ctrl + w, +` / `-` | **Resize Height**| Increase / decrease window height |

---

## 🧠 3. LSP & Code Intelligence (Go to Definition / Usage)
These keymaps run automatically when editing supported languages (e.g., Kotlin, Python, Lua).

| Keybinding | Action | Description |
|---|---|---|
| `gd` | **Go to Definition** | Jump to where the class/variable/function is defined |
| `gr` | **Find References** | List all usages of the symbol under cursor |
| `gi` | **Go to Implementation**| Jump to interface implementation |
| `K` (Capital) | **Hover Docs** | Show type signature and documentation in a popup |
| `<leader>rn` (`Space + r + n`) | **Rename Symbol** | Rename variable/class project-wide |
| `<leader>ca` (`Space + c + a`) | **Code Action** | Open quick-fix actions (e.g. import suggestions) |
| `<leader>f` (`Space + f`) | **Format** | Format current file using LSP |
| `]d` / `[d` | **Diagnostics** | Jump to Next / Previous error or warning |
| `Ctrl + o` | **Jump Back** | Go back to your previous cursor location |
| `Ctrl + i` | **Jump Forward** | Go forward to your next cursor location |

---

## ✍️ 4. Common Editing & File Operations
### File Basics
*   `:w` $\rightarrow$ Save (write) current file.
*   `:wa` $\rightarrow$ Save all open files.
*   `:q` $\rightarrow$ Quit.
*   `:wq` / `:x` $\rightarrow$ Save and quit.
*   `:e path/to/file` $\rightarrow$ Open/create a file.

### Undo & Redo
*   `u` $\rightarrow$ Undo last change.
*   `Ctrl + r` $\rightarrow$ Redo last change.

### Copy & Paste (System Clipboard Connected)
*   `y` $\rightarrow$ Yank (copy) selected text.
*   `yy` $\rightarrow$ Yank the current line.
*   `d` $\rightarrow$ Delete (cut) selected text.
*   `dd` $\rightarrow$ Delete the current line.
*   `p` $\rightarrow$ Paste copied/deleted text after cursor.
*   `P` $\rightarrow$ Paste copied/deleted text before cursor.
*(Since `clipboard = "unnamedplus"` is enabled, your copies/cuts sync with MacOS command-c / command-v!)*

---

## 🚀 5. Mastering Motions (Move Faster)
### Word-level Movements
*   `w` $\rightarrow$ Jump forward to the start of the next word.
*   `b` $\rightarrow$ Jump backward to the start of the previous word.
*   `e` $\rightarrow$ Jump forward to the end of the next word.

### Line-level Movements
*   `0` (zero) $\rightarrow$ Jump to the absolute beginning of the line.
*   `^` $\rightarrow$ Jump to the first non-blank character of the line.
*   `$` $\rightarrow$ Jump to the end of the line.
*   `%` $\rightarrow$ Jump between matching brackets `()`, `{}`, `[]`.

### Screen Jumps
*   `Ctrl + d` $\rightarrow$ Scroll half-screen Down.
*   `Ctrl + u` $\rightarrow$ Scroll half-screen Up.
*   `gg` $\rightarrow$ Go to the very top of the file.
*   `G` $\rightarrow$ Go to the very bottom of the file.
*   `[Number]j` / `[Number]k` $\rightarrow$ Jump down/up by relative lines (e.g. `12j` jumps down 12 lines).

### Visual Selection Modes
*   `v` $\rightarrow$ Enter Visual mode (character selection).
*   `V` (Capital) $\rightarrow$ Enter Visual Line mode (line selection).
*   `Ctrl + v` $\rightarrow$ Enter Visual Block mode (column selection).
    *   *Tip for multi-line editing:* Press `Ctrl + v`, highlight down, press `Shift + i`, type something (like comments `// `), and hit `Esc`. It will apply to all lines!

---

## 🔁 6. Search and Replace
*   `/text` $\rightarrow$ Search for `text` in current file.
    *   Press `n` to go to the next match, `N` to go to the previous match.
*   `:s/old/new/g` $\rightarrow$ Replace `old` with `new` on the current line.
*   `:%s/old/new/g` $\rightarrow$ Replace `old` with `new` in the entire file.
*   `:%s/old/new/gc` $\rightarrow$ Replace in entire file with a prompt to confirm each change (`y` or `n`).

---

## 🐙 7. Git Integration (Gitsigns)
Your gutter (left margin) will show:
*   `+` (Green) $\rightarrow$ Added lines.
*   `~` (Blue) $\rightarrow$ Modified lines.
*   `_` or `-` (Red) $\rightarrow$ Deleted lines.

| Keybinding | Action | Description |
|---|---|---|
| `]c` | **Next Change** | Jump to the next changed block of code |
| `[c` | **Prev Change** | Jump to the previous changed block of code |
| `<leader>hp` (`Space + h + p`) | **Preview Change** | Open a popup showing the diff of the current block |
| `<leader>hd` (`Space + h + d`) | **Diff File** | Open a side-by-side vertical diff of the current file |

