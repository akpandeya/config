# Shared shell aliases. Sourced from ~/.zshrc by setup-dev-env.sh.

alias k=kubectl
alias vim=nvim

# Launch Claude Code against GLM 5 via the HelloFresh AI model router
claude-glm() {
    claude --model bedrock/zai.glm-5 "$@"
}

# mdserve <dir>: serve any folder of markdown as a browsable site
# (mkdocs + material theme). Relative ./x.md#anchor links and mermaid
# diagrams render; live-reloads on save. Uses a throwaway mkdocs.yml so
# no per-project config is needed. Requires: uv tool install mkdocs --with mkdocs-material
mdserve() {
    local dir="${1:-.}"
    dir="$(cd "$dir" 2>/dev/null && pwd)" || { echo "mdserve: no such directory: ${1:-.}" >&2; return 1; }
    local tmp
    tmp="$(mktemp -d)" || return 1
    cat > "$tmp/mkdocs.yml" <<EOF
site_name: markdown preview
docs_dir: $dir
theme:
  name: material
  palette:
    scheme: slate
markdown_extensions:
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - tables
  - toc:
      permalink: true
EOF
    mkdocs serve --config-file "$tmp/mkdocs.yml" -a localhost:8642
    rm -rf "$tmp"
}

# himalaya-vim: jump straight into the unread listing for an account.
# Toggle to all / back inside the buffer with `a` / `u`.
alias mp='nvim +"HimalayaAccountUnread personal"'
alias mw='nvim +"HimalayaAccountUnread work"'

# Dynamically sync local project-specific skills to Gemini's user-level plugin
update_gemini_skills() {
    local gemini_skills_dir="$HOME/.gemini/config/plugins/personal-skills/skills"
    local symlink target skill_dir name
    [ -d "$gemini_skills_dir" ] || return 0

    # Clean up old project-level symlinks pointing outside our personal config repo
    find "$gemini_skills_dir" -type l 2>/dev/null | while read -r symlink; do
        target=$(readlink "$symlink")
        if [[ "$target" != *"/code/personal/config/claude/skills"* ]]; then
            rm "$symlink"
        fi
    done

    # $HOME/.claude/skills holds user-level skills, not project ones. Without
    # this guard, opening a shell in $HOME links them into the gemini dir, and
    # worse: BSD ln follows an existing symlink-to-dir target and creates the
    # new link *inside* it — which is how circular <skill>/<skill> symlinks
    # kept appearing in the config repo.
    [ "$PWD" != "$HOME" ] || return 0

    # Symlink current repository's .claude/skills/* if they exist
    if [ -d "./.claude/skills" ]; then
        for skill_dir in ./.claude/skills/*; do
            [ -d "$skill_dir" ] || continue
            name=$(basename "$skill_dir")
            # -h: replace an existing symlink target instead of following it
            # into the directory it points at.
            ln -sfnh "$(pwd)/.claude/skills/$name" "$gemini_skills_dir/$name"
        done
    fi
}


# Add to zsh chpwd hooks if in zsh
if [ -n "$ZSH_VERSION" ]; then
    typeset -ag chpwd_functions
    if [[ ! " ${chpwd_functions[*]} " =~ " update_gemini_skills " ]]; then
        chpwd_functions+=(update_gemini_skills)
    fi
    # Run once at startup/sourcing
    update_gemini_skills

    # dev: fuzzy repo picker + AI harness launcher (dev/cc/oc + repo
    # shortcuts defined in dev-shortcuts.conf). zsh only.
    _aliases_dir="${${(%):-%x}:A:h}"
    [ -f "$_aliases_dir/dev.sh" ] && source "$_aliases_dir/dev.sh"
    [ -f "$_aliases_dir/pg.sh" ] && source "$_aliases_dir/pg.sh"
    unset _aliases_dir
fi

