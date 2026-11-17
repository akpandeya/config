# Scoped git identity + signing

Two-identity git setup driven by `setup-dev-env.sh`. Nothing here is installed
by hand and nothing prompts for your name or email.

## How it is wired

1. `setup-dev-env.sh` sources `emails.local.env` (gitignored) for
   `PERSONAL_EMAIL` and `WORK_EMAIL`. If that file is absent it falls back to
   the identity currently in effect (`~/.gitconfig-personal`, then
   `git config --global user.email`) and only prompts if *that* is empty too.
2. The scoped templates are rendered with `sed`:

   | Template | Rendered to | When |
   |---|---|---|
   | `private/.gitconfig.tmpl` | `~/.gitconfig-personal` | always |
   | `work/.gitconfig.tmpl` | `~/.gitconfig-work` | `SETUP_MODE=work` |

3. The top-level `~/.gitconfig` is patched with `git config --global` — only the
   keys this repo owns (identity, signing, `includeIf`, defaults). Anything else
   you already set (`credential.helper`, aliases, `core.editor`) is preserved.
4. `includeIf` routes each directory tree at its fragment:

```gitconfig
[includeIf "gitdir:~/code/personal/"]
    path = ~/.gitconfig-personal
[includeIf "gitdir:~/code/work/"]
    path = ~/.gitconfig-work
```

## SSH signing

Signing uses the on-disk private keys directly (`gpg.ssh.program` is
deliberately unset — routing through 1Password's `op-ssh-sign` was unstable).
Personal commits sign with `~/.ssh/id_dipus_macbook`, work commits with
`~/.ssh/id_hf_thinkpad`. `~/.config/git/allowed_signers` maps each email to its
pubkey so `git log --show-signature` verifies locally.

## Re-running

Safe and idempotent. `SETUP_MODE` is inferred from the machine (`work` when
`~/.gitconfig-work` or the work `includeIf` exists), so a plain re-run never
drops your work identity. Pass `SETUP_MODE=work|personal` to override.

## Troubleshooting

**Wrong email in a repo:**

```bash
git config --show-origin user.email   # which file is winning
git config --show-origin includeIf.gitdir:~/code/work/.path
```

Check the repo actually lives under `~/code/work/` or `~/code/personal/` — the
`includeIf` glob matches on that path.

**Signature not verifying:** confirm the email/`allowed_signers` entry matches and
that `~/.ssh/id_*.pub` exists for the key named in that fragment.

**Setup ran as the wrong profile:** `~/.gitconfig-work` is removed on a
`personal` run. Re-run with `SETUP_MODE=work` to restore it.
