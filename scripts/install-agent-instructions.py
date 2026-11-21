#!/usr/bin/env python3
"""Compose shared, personal and work instructions for local AI tools."""

import argparse
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
TARGETS = {
    "claude": ".claude/CLAUDE.md",
    "opencode": ".config/opencode/AGENTS.md",
    "gemini": ".gemini/GEMINI.md",
    "copilot": ".copilot/copilot-instructions.md",
    "pi": ".pi/agent/AGENTS.md",
}
PROFILE_TARGETS = {
    profile: {
        "pi": f".agent/profiles/{profile}/pi/AGENTS.md",
        "opencode": f".agent/profiles/{profile}/opencode/AGENTS.md",
        "claude": f".agent/profiles/{profile}/claude/CLAUDE.md",
        "copilot": f".agent/profiles/{profile}/copilot/copilot-instructions.md",
    }
    for profile in ("personal", "work")
}


def write_atomic(path, content):
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a generated-file symlink: {path}")
    if path.exists() and path.read_text() == content:
        path.chmod(0o600)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def link_preserving_existing(target, source):
    if target.is_symlink() and target.resolve() == source.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        backup = target.with_name(target.name + ".before-agent-context")
        index = 1
        while backup.exists() or backup.is_symlink():
            backup = target.with_name(target.name + f".before-agent-context.{index}")
            index += 1
        target.rename(backup)
        print(f"Preserved previous instructions: {backup}")
    target.symlink_to(source)


def migrate_work_skill_links(home, dry_run=False):
    """Move work-owned links out of generic Claude/Agy skill discovery."""
    work_root = (home / "code/work").resolve()
    mappings = [
        (home / ".claude/skills", home / ".agent/profiles/work/claude/skills"),
        (home / ".gemini/config/plugins/personal-skills/skills",
         home / ".agent/profiles/work/agy-home/.gemini/config/plugins/personal-skills/skills"),
    ]
    for source_root, target_root in mappings:
        if not source_root.is_dir():
            continue
        if source_root.is_symlink() and source_root.resolve().is_relative_to(work_root):
            raise ValueError(f"Unscoped skill directory links into work; split it manually: {source_root}")
        for source in sorted(source_root.iterdir()):
            if not source.is_symlink():
                continue
            resolved = source.resolve()
            if not resolved.is_relative_to(work_root):
                continue
            target = target_root / source.name
            if dry_run:
                print(f"Would move work skill link {source} -> {target}")
                continue
            target_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target_root.resolve() != target_root:
                raise ValueError(f"Scoped skill destination must not contain symlinks: {target_root}")
            if target.is_symlink() and target.resolve() == resolved:
                source.unlink()
                continue
            if target.exists() or target.is_symlink():
                backup = target.with_name(target.name + ".before-agent-context")
                index = 1
                while backup.exists() or backup.is_symlink():
                    backup = target.with_name(target.name + f".before-agent-context.{index}")
                    index += 1
                target.rename(backup)
                print(f"Preserved previous scoped skill: {backup}")
            source.rename(target)
            print(f"Moved work skill link into scoped profile: {target}")


def install(home, root=ROOT, work_context=None, dry_run=False):
    home = home.expanduser().resolve()
    if work_context is None:
        candidate = home / ".hf-context/AGENTS.md"
        if candidate.is_symlink() and not candidate.exists():
            raise ValueError(f"Broken private-context link: {candidate}")
        work_context = candidate if candidate.exists() else None
    elif not work_context.is_file():
        raise ValueError(f"Private context does not exist: {work_context}")

    shared_sources = [root / "opencode/AGENTS.md", root / "agents/communication.md"]
    shared = "\n\n".join(path.read_text().strip() for path in shared_sources) + "\n"
    combined = shared
    if work_context is not None:
        combined += "\n" + work_context.read_text().strip() + "\n"
    # Imports are flattened here so tools without @-import support get the same text.
    if any(line.startswith("@") for line in combined.splitlines()):
        raise ValueError("Instruction sources must be self-contained, without @ imports")
    rtk = (root / "claude/RTK.md").read_text()
    pi_work_extra = (root / "pi/AGENTS-extra.md").read_text()
    memory = {
        "personal": (root / "agents/personal-memory.md").read_text(),
        "work": (root / "agents/work-memory.md").read_text(),
    }
    prepared = []
    header = "<!-- Generated by install-agent-instructions.py; edit the sources. -->\n\n"

    def prepare(name, destination, content, scoped=False):
        generated = home / ".config/agent-context" / f"{name}.md"
        target = home / destination
        if scoped and target.parent.resolve() != target.parent:
            raise ValueError(f"Scoped instruction destination must not contain symlinks: {target.parent}")
        if generated.is_symlink() or (generated.exists() and not generated.is_file()):
            raise ValueError(f"Generated destination is not a regular file: {generated}")
        if generated.resolve().is_relative_to(root.resolve()):
            raise ValueError("Generated instructions must stay outside the source repository")
        if target.parent.resolve().is_relative_to(root.resolve()):
            raise ValueError("Global instruction destinations must stay outside the source repository")
        prepared.append((name, content, generated, target))

    # Plain harnesses get no scoped-memory protocol. Private work context
    # requires a scoped work launcher, never an ordinary personal invocation.
    for harness, destination in TARGETS.items():
        content = header + shared
        if harness in ("claude", "opencode"):
            content += "\n" + rtk
        prepare(harness, destination, content)

    for profile, harnesses in PROFILE_TARGETS.items():
        for harness, destination in harnesses.items():
            content = header + (shared if profile == "personal" else combined)
            if harness in ("claude", "opencode"):
                content += "\n" + rtk
            if harness == "pi" and profile == "work":
                content += "\n" + pi_work_extra
            content += "\n" + memory[profile]
            prepare(f"{harness}-{profile}", destination, content, scoped=True)

    migrate_work_skill_links(home, dry_run=dry_run)
    for name, content, generated, target in prepared:
        if dry_run:
            print(f"Would compose {name} instructions and link {target} -> {generated}")
        else:
            write_atomic(generated, content)
            link_preserving_existing(target, generated)
            print(f"Installed {name} instructions: {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--work-context", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        install(args.home, work_context=args.work_context, dry_run=args.dry_run)
    except (OSError, ValueError) as error:
        print(f"Instructions not installed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
