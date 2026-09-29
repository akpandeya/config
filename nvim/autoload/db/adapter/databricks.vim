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
