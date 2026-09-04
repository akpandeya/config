# dev: fuzzy repo picker + AI harness launcher (zsh only).
#
# Commands:
#   dev [query]     fzf over all git repos under $DEV_CODE_ROOT (default
#                   ~/code), shortcuts pinned on top marked "*".
#                   enter asks for a harness, ctrl-o = opencode,
#                   ctrl-c = Claude Code.
#   cc [target]     Claude Code (claude --dangerously-skip-permissions)
#   oc [target]     opencode (opencode --auto)
#                   No target: open the harness in the current directory.
#                   Target: shortcut name, repo basename/path, or fuzzy query.
#   <shortcut>      e.g. `fda`: cd into the repo + its default harness.
#
# Shortcuts live in dev-shortcuts.conf next to this file — see its header.
# To add another harness, edit _dev_launch and the no-arg case in _dev_go.

# zsh only (uses `read -k` and prompt expansion to locate this file)
[ -n "$ZSH_VERSION" ] || return 0

_dev_dir() {
    print -r -- "${${(%):-%x}:A:h}"
}

_dev_code_root() {
    local root="${DEV_CODE_ROOT:-$HOME/code}"
    print -r -- "${root%/}"
}

_dev_need_fzf() {
    if ! command -v fzf >/dev/null 2>&1; then
        echo "dev: fzf not found — install it with: brew install fzf" >&2
        return 1
    fi
}

# --- data -----------------------------------------------------------------

# Emits one "name <TAB> relpath <TAB> harness" line per shortcut.
# Re-reads dev-shortcuts.conf on every call, so edits apply instantly.
_dev_shortcuts() {
    local conf="$(_dev_dir)/dev-shortcuts.conf"
    [ -f "$conf" ] || return 0
    # NOTE: never name a zsh local "path" — it is tied to $PATH.
    local line name rest rpath harness
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%#*}"
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        if [ -z "$line" ] || [[ "$line" != *=* ]]; then continue; fi
        name="${line%%=*}"
        rest="${line#*=}"
        name="${name#"${name%%[![:space:]]*}"}"; name="${name%"${name##*[![:space:]]}"}"
        rest="${rest#"${rest%%[![:space:]]*}"}"; rest="${rest%"${rest##*[![:space:]]}"}"
        rpath="$rest"; harness=""
        if [[ "$rest" == *:* ]]; then
            rpath="${rest%%:*}"
            harness="${rest#*:}"
            rpath="${rpath%"${rpath##*[![:space:]]}"}"
            harness="${harness#"${harness%%[![:space:]]*}"}"
            harness="${harness%"${harness##*[![:space:]]}"}"
        fi
        if [ -z "$name" ] || [ -z "$rpath" ]; then continue; fi
        printf '%s\t%s\t%s\n' "$name" "$rpath" "$harness"
    done < "$conf"
}

# Repo paths relative to the code root: dirs containing .git, max depth 4
# (covers <group>/<repo> plus the odd deeper nesting; .git -prune keeps
# submodules out).
_dev_repos() {
    local root="$(_dev_code_root)"
    [ -d "$root" ] || return 1
    find "$root" -maxdepth 4 -name .git -prune 2>/dev/null | while IFS= read -r gitdir; do
        print -r -- "${${gitdir%/.git}#$root/}"
    done | sort
}

# Picker lines: shortcuts first ("* name -> relpath"), then all repos.
_dev_list() {
    # NOTE: zsh runs the last pipeline segment in the current shell, so a
    # variable named "path" here would clobber $PATH for _dev_repos below.
    _dev_shortcuts | while IFS=$'\t' read -r name rpath harness; do
        [ -n "$name" ] && printf '* %s -> %s\n' "$name" "$rpath"
    done
    _dev_repos
}

# Picker line -> relpath.
_dev_sel_to_rel() {
    local sel="$1"
    if [[ "$sel" == \*\ * ]]; then
        sel="${sel##* -> }"
    fi
    sel="${sel#"${sel%%[![:space:]]*}"}"
    sel="${sel%"${sel##*[![:space:]]}"}"
    print -r -- "$sel"
}

# --- launching --------------------------------------------------------------

_dev_launch() {
    local harness="$1" dir="$2"
    if [ ! -d "$dir" ]; then
        echo "dev: no such directory: $dir" >&2
        return 1
    fi
    cd "$dir" || return 1
    case "$harness" in
        opencode) opencode --auto ;;
        claude)   claude --dangerously-skip-permissions ;;
        *) echo "dev: unknown harness '$harness' (expected opencode or claude)" >&2; return 1 ;;
    esac
}

_dev_pick_harness() {
    local choice
    while true; do
        read -k 1 "choice?Harness: [o]pencode / [c]laude / [q]uit? "
        echo
        case "$choice" in
            o|O) print -r -- opencode; return 0 ;;
            c|C) print -r -- claude;   return 0 ;;
            q|Q|$'\n'|$'\r') return 1 ;;
        esac
    done
}

# --- resolution (for cc/oc <target>) ----------------------------------------

# Resolve a target (shortcut name / repo path / repo basename / fuzzy query)
# to a relpath. Prints the relpath; returns non-zero if cancelled/unresolved.
_dev_resolve() {
    local q="$1"
    if [ -z "$q" ]; then return 1; fi

    # 1. exact shortcut name
    local name rpath harness
    while IFS=$'\t' read -r name rpath harness; do
        if [ "$name" = "$q" ]; then
            print -r -- "$rpath"
            return 0
        fi
    done < <(_dev_shortcuts)

    # 2. exact repo relpath, or unique repo basename
    local rel
    local -a basename_matches
    basename_matches=()
    while IFS= read -r rel; do
        if [ "$rel" = "$q" ]; then
            print -r -- "$rel"
            return 0
        elif [ "${rel##*/}" = "$q" ]; then
            basename_matches+=("$rel")
        fi
    done < <(_dev_repos)
    if [ ${#basename_matches[@]} -eq 1 ]; then
        print -r -- "${basename_matches[1]}"
        return 0
    fi

    # 3. fuzzy: one hit -> jump straight there, otherwise open the picker
    _dev_need_fzf || return 1
    local list filtered sel count
    list="$(_dev_list)"
    filtered="$(print -r -- "$list" | fzf --filter="$q")"
    count=$(print -r -- "$filtered" | grep -c .)
    if [ "$count" -eq 1 ]; then
        sel="$filtered"
    else
        sel="$(print -r -- "$list" | fzf --query="$q" --prompt='dev> ' \
            --height=40% --reverse --header='select repo')" || return 1
    fi
    if [ -z "$sel" ]; then return 1; fi
    _dev_sel_to_rel "$sel"
}

# --- commands ---------------------------------------------------------------

dev() {
    _dev_need_fzf || return 1
    local root="$(_dev_code_root)"
    if [ ! -d "$root" ]; then
        echo "dev: code root not found: $root (set DEV_CODE_ROOT)" >&2
        return 1
    fi
    local out key sel rel harness
    out="$(_dev_list | fzf --expect=ctrl-o,ctrl-c --query="$*" \
        --prompt='dev> ' --height=40% --reverse \
        --header='enter: pick harness | ctrl-o: opencode | ctrl-c: claude')" || return 0
    key="$(head -n 1 <<< "$out")"
    sel="$(sed -n 2p <<< "$out")"
    if [ -z "$sel" ]; then return 0; fi
    rel="$(_dev_sel_to_rel "$sel")"
    case "$key" in
        ctrl-o) harness=opencode ;;
        ctrl-c) harness=claude ;;
        *)
            harness="$(_dev_pick_harness)" || { echo "dev: cancelled"; return 0; }
            ;;
    esac
    echo "dev: -> $root/$rel"
    _dev_launch "$harness" "$root/$rel"
}

_dev_go() {
    local harness="$1"
    shift
    if [ $# -eq 0 ]; then
        # No target: open the harness in the current directory.
        case "$harness" in
            opencode) opencode --auto ;;
            claude)   claude --dangerously-skip-permissions ;;
        esac
        return
    fi
    local rel
    rel="$(_dev_resolve "$*")" || return 1
    if [ -z "$rel" ]; then return 1; fi
    echo "dev: -> $(_dev_code_root)/$rel"
    _dev_launch "$harness" "$(_dev_code_root)/$rel"
}

cc() { _dev_go claude "$@"; }
oc() { _dev_go opencode "$@"; }

# --- bare shortcut commands ---------------------------------------------------

# Look up a shortcut fresh from the conf, then cd (+ default harness).
_dev_shortcut_run() {
    local target="$1"
    local name rpath harness
    while IFS=$'\t' read -r name rpath harness; do
        if [ "$name" = "$target" ]; then
            if [ -n "$harness" ]; then
                _dev_launch "$harness" "$(_dev_code_root)/$rpath"
            else
                cd "$(_dev_code_root)/$rpath"
            fi
            return
        fi
    done < <(_dev_shortcuts)
    echo "dev: shortcut '$target' not found in dev-shortcuts.conf" >&2
    return 1
}

# Define one bare command per shortcut (runs at shell startup; new shortcuts
# need a new shell or `source ~/.zshrc` — cc/oc/dev see them instantly).
_dev_define_shortcuts() {
    local name rpath harness
    while IFS=$'\t' read -r name rpath harness; do
        if [ -z "$name" ]; then continue; fi
        case "$name" in
            dev|cc|oc)
                echo "dev: shortcut '$name' ignored (reserved name)" >&2
                continue
                ;;
        esac
        if whence -w "$name" >/dev/null 2>&1; then
            echo "dev: warning — shortcut '$name' shadows existing command ($(whence -w "$name"))" >&2
        fi
        eval "${name}() { _dev_shortcut_run ${(q)name}; }"
    done < <(_dev_shortcuts)
}

_dev_define_shortcuts
