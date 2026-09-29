" Snowflake via the `snow` CLI — not snowsql. Shadows vim-dadbod's built-in
" snowsql adapter (this autoload dir is earlier in &runtimepath).
"
" URL: snowflake:<connection>   e.g. snowflake:hf
" The <connection> is a stanza from the snowflake CLI config
" (~/Library/Application Support/snowflake/connections.toml); HF uses SSO,
" so the first query of a session pops a browser for auth.
"
" Query runs non-interactively: snow sql -c <conn> -f <queryfile> --format TABLE
" (TABLE renders an aligned grid in the dbout; CSV was unreadable for tables
" with VARIANT columns — snow embeds the JSON with doubled-quote escaping).
function! db#adapter#snowflake#input(url, in) abort
  let conn = matchstr(a:url, '^snowflake:\zs[^/?#]*')
  return ['snow', 'sql', '-c', empty(conn) ? 'hf' : conn,
        \ '-f', a:in, '--format', 'TABLE']
endfunction

" Skip dadbod's auth probe (it would run the CLI against a blank file);
" auth is the snow CLI's cached SSO token, not a dadbod password.
function! db#adapter#snowflake#auth_input() abort
  return v:false
endfunction

" Browsable table list for DBUI + dadbod-completion: fully-qualified names
" from a curated catalogue file (scripts/refresh-db-catalogue.sh, run via
" :SqlCatalogueRefresh).
function! db#adapter#snowflake#tables(conn) abort
  let catalogue = expand('~/.local/share/nvim/db-catalogue/snowflake.tables')
  return filereadable(catalogue) ? readfile(catalogue) : []
endfunction
