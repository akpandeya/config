# pg: fuzzy service picker + nvim SQL scratch / psql launcher (zsh only).
#
#   fpsql [svc] [name]  fzf over the [stanza] names in $PGSERVICEFILE
#                       (default ~/.pg_service.conf), then opens the
#                       per-service SQL scratch in nvim bound to the service
#                       via vim-dadbod (:SqlScratch). Optional second word
#                       picks the scratch file: `fpsql nomos review` →
#                       nomos/review.sql. Exact stanza name skips the picker.
#   fpsql -p [svc]      psql instead: `psql service=<name>`. Args from the
#                       first '-...' one onward are passed through to psql:
#                       `fpsql -p envelope-man -c '\dt'`.
#   psql service=<TAB>  completes stanza names from the same file.

# zsh only (completion registration + ${(q) quoting)
[ -n "$ZSH_VERSION" ] || return 0

_pg_service_file() {
    print -r -- "${PGSERVICEFILE:-$HOME/.pg_service.conf}"
}

# One "name<TAB>host<TAB>dbname" line per [stanza] in the service file.
_pg_services() {
    local conf
    conf="$(_pg_service_file)"
    [ -f "$conf" ] || return 0
    awk '
        function flush() { if (name != "") printf "%s\t%s\t%s\n", name, host, db }
        /^\[/ { flush(); name = $0; gsub(/[\[\]]/, "", name); host = ""; db = ""; next }
        /^host=/   { host = substr($0, 6) }
        /^dbname=/ { db = substr($0, 8) }
        END { flush() }
    ' "$conf"
}

# fpsql [-p] [svc] [name]: fuzzy-pick a service, then open the per-service
# nvim scratchpad against it (default), or psql with -p. Words before the
# first '-...' form the fzf pre-query (exact stanza name jumps straight in),
# the rest go to psql (`fpsql -p nomos -c '\dt'`); with scratch mode, a second
# word picks the scratch file (`fpsql nomos review`).
fpsql() {
    command -v fzf >/dev/null 2>&1 || {
        echo "fpsql: fzf not found — install it with: brew install fzf" >&2
        return 1
    }
    # default: open the nvim SQL scratch; -p runs psql (-e kept as an alias)
    local psql_mode=0
    if [ "$1" = "-p" ]; then
        psql_mode=1
        shift
    elif [ "$1" = "-e" ]; then
        shift
    fi
    local -a query_parts flags
    query_parts=()
    flags=()
    while [ $# -gt 0 ]; do
        case "$1" in
            -*) flags+=("$@"); break ;;
            *)  query_parts+=("$1"); shift ;;
        esac
    done
    local q="${query_parts[*]}"
    if [ "$psql_mode" -eq 0 ] && (( ${#query_parts[@]} > 1 )); then
        # `fpsql nomos review`: only the first word names the service
        q="${query_parts[1]}"
    fi
    local sel
    if [ -n "$q" ] && _pg_services | cut -f1 | grep -qx "$q"; then
        sel="$q"
    else
        sel="$(_pg_services | fzf --query="$q" --delimiter=$'\t' \
            --with-nth=1 --prompt='fpsql> ' --height=40% --reverse \
            --header='psql service=<name>')" || return 1
    fi
    [ -z "$sel" ] && return 1
    sel="${sel%%$'\t'*}"
    if [ "$psql_mode" -eq 0 ]; then
        # extra words after the service name pick the scratch file
        local -a scratch_args=("$sel")
        (( ${#query_parts[@]} > 1 )) && scratch_args+=("${(j: :)query_parts[2,-1]}")
        echo "fpsql: -> nvim +SqlScratch ${scratch_args[*]}"
        nvim "+SqlScratch ${(j: :)scratch_args}"
        return
    fi
    echo "fpsql: -> psql service=$sel"
    psql "service=$sel" "${flags[@]}"
}

# --- completion ---------------------------------------------------------------

# Complete stanza names for fpsql and for `psql service=<prefix>`.
_pg_service_name_comp() {
    local -a names
    names=("${(@f)$(_pg_services | cut -f1)}")
    _describe -t pg-service 'pg service' names
}

# Wrapper around the stock psql completion: only handles `service=...`
# (the -P prefix keeps `service=` on the line and is ignored for matching);
# everything else falls through to the real _psql.
_pg_psql() {
    if [[ "${words[CURRENT]}" == service=* ]]; then
        local -a names
        names=("${(@f)$(_pg_services | cut -f1)}")
        compadd -P 'service=' -S '' -- "${names[@]}"
    else
        _psql "$@"
    fi
}

if (( $+functions[compdef] )); then
    compdef _pg_service_name_comp fpsql
    compdef _pg_psql psql
fi
