# pg: fuzzy psql launcher + service-name completion (zsh only).
#
#   fpsql [query]   fzf over the [stanza] names in $PGSERVICEFILE
#                   (default ~/.pg_service.conf), then opens
#                   `psql service=<name>`. Args from the first '-...' one
#                   onward are passed through to psql:
#                   `fpsql envelope-man -c '\dt'`.
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

# fpsql [query]: fuzzy-pick a service, then exec psql against it.
# Words before the first '-...' form the fzf pre-query (exact stanza name
# jumps straight in), the rest go to psql (`fpsql nomos -c '\dt'`).
fpsql() {
    command -v fzf >/dev/null 2>&1 || {
        echo "fpsql: fzf not found — install it with: brew install fzf" >&2
        return 1
    }
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
