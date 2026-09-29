" Databricks (Photon SQL warehouse) via hf-photon, which reads its credentials
" from ~/.config/hf-workbench/photon.env. Only one profile exists, so the URL
" is a label rather than a connection: databricks:photon
"
" Query runs non-interactively: hf-photon -f <queryfile>   (output is TSV)
function! db#adapter#databricks#input(url, in) abort
  return ['hf-photon', '-f', a:in]
endfunction

" Skip dadbod's auth probe (it would run the CLI against a blank file and
" spew 'Error: empty SQL'); hf-photon carries its own credentials.
function! db#adapter#databricks#auth_input() abort
  return v:false
endfunction

" Browsable table list for DBUI + dadbod-completion: fully-qualified names
" from a curated catalogue file (scripts/refresh-db-catalogue.sh, run via
" :SqlCatalogueRefresh). The glue catalog has ~1000 schemas and no
" information_schema, so a live SHOW TABLES sweep here would block nvim.
function! db#adapter#databricks#tables(conn) abort
  let catalogue = expand('~/.local/share/nvim/db-catalogue/databricks.tables')
  return filereadable(catalogue) ? readfile(catalogue) : []
endfunction
