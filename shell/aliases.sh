# Shared shell aliases. Sourced from ~/.zshrc by setup-dev-env.sh.

alias k=kubectl
alias vim=nvim

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

    # Symlink current repository's .claude/skills/* if they exist
    if [ -d "./.claude/skills" ]; then
        for skill_dir in ./.claude/skills/*; do
            [ -d "$skill_dir" ] || continue
            name=$(basename "$skill_dir")
            ln -sf "$(pwd)/.claude/skills/$name" "$gemini_skills_dir/$name"
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
fi

